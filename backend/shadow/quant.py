"""8-bit models for a CPU-only laptop: weight-only int8 Linear layers, and the CPU thread budget.

The int8 Linear is our own (Int8Linear), not torch's dynamic qint8: that one's memory depends on the quantised engine,
and the Windows CPU wheel has only oneDNN, whose packed Linear keeps the int8 weight twice (each int8 model cost about
2x its weights there, ~700 MB more than Linux across the three models). Int8Linear stores the int8 weight once and
dequantises it per call, the same on every platform."""
from __future__ import annotations
import gc
import os
import re
import logging
from pathlib import Path
from shadow.config import Settings
from shadow.memory import trim_heap

log = logging.getLogger(__name__)


QUANT_FORMAT = 2          # bump on any change to the quantisation recipe or to what is stored: stored models are rebuilt
                          # (the Windows bootstrap reads this line with a regex: keep it `QUANT_FORMAT = <int>`)
_stored: set[Path] = set()  # the stored int8 copies this process read or wrote; prepare lists them in its manifest


def stored_int8_paths() -> list[Path]:
    return sorted(_stored)


def int8_cache_path(key: str) -> Path:
    """Where the quantised model for `key` is kept: <models dir>/int8/, named by the key, QUANT_FORMAT and torch's version.
    The caller puts the versions of the library whose classes are pickled (transformers, torchaudio) in the key."""
    import torch
    from shadow.ingest.punct import models_cache_dir
    return models_cache_dir() / "int8" / (re.sub(r"[^A-Za-z0-9._-]", "_", f"{key}-q{QUANT_FORMAT}-torch{torch.__version__}") + ".pt")


def remove_stale_int8(key: str, keep: Path) -> None:
    """Delete the stored int8 copies of the same model (the key without its trailing library-version part) that were
    made for other versions of torch, the library or the recipe: each is hundreds of MB on a laptop disk. Never `keep`."""
    model = re.sub(r"[^A-Za-z0-9._-]", "_", key).rpartition("-")[0]
    if not model:
        return
    pattern = re.compile(re.escape(model) + r"-[A-Za-z_]+\d[^-]*-q\d+-torch[^-]*\.pt")
    for f in keep.parent.glob("*.pt"):
        if f != keep and pattern.fullmatch(f.name):
            try:
                f.unlink()
                log.info("removed the stale int8 model %s", f.name)
            except OSError:
                log.warning("could not remove the stale int8 model %s", f.name, exc_info=True)


def cached_int8(key: str, build):
    """The quantised module build() returns, kept on disk after the first build: a later load reads the int8 weights
    only (about a quarter of the fp32 size) instead of loading fp32 and quantising, whose peak is 3x higher.
    The whole module is pickled, so the key must name the library versions; an unreadable file is rebuilt."""
    import torch
    path = int8_cache_path(key)
    root = path.parent
    if path.exists():
        try:
            model = torch.load(path, map_location="cpu", weights_only=False).eval()
            _stored.add(path)
            return model
        except Exception:
            log.exception("the stored int8 model %s is unreadable; rebuilding it", path.name)
    model = build()
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    try:
        from torch.nn.utils import parametrize
        for m in model.modules():                   # a parametrised weight (weight norm) cannot be pickled: fold it in
            for name in list(getattr(m, "parametrizations", {})):
                parametrize.remove_parametrizations(m, name, leave_parametrized=True)
            m._load_state_dict_pre_hooks.clear()    # weight norm's compatibility hook is a local function, not picklable
        root.mkdir(parents=True, exist_ok=True)
        torch.save(model, tmp)
        os.replace(tmp, path)
        _stored.add(path)
        remove_stale_int8(key, path)
    except Exception:
        log.exception("could not store the int8 model %s", path.name)
        tmp.unlink(missing_ok=True)
    return model


def quantize_linear(module):
    """Every exact torch.nn.Linear becomes an Int8Linear (int8 weights, symmetric per output row; fp32 activations);
    eval mode. The fp32 weights are freed once the caller drops its reference."""
    import torch
    int8_linear = _int8_linear_class()
    # Weights read lazily from a checkpoint stay memory-mapped to its file while any tensor refers to them (the sounds
    # model kept 1.2 GB resident after quantising). So every other tensor is copied out of the mapping, each Linear is
    # read into its own int8 copy and its fp32 weight emptied (one layer at a time), and the mapping goes.
    with torch.no_grad():
        for m in module.modules():
            if type(m) is not torch.nn.Linear:
                for t in [*m.parameters(recurse=False), *m.buffers(recurse=False)]:
                    t.data = t.data.clone()
        uses: dict[int, int] = {}                            # over every module: a Linear weight may be tied to
        for m in module.modules():                           # an Embedding (an LM head), not only to another Linear
            for p in m.parameters(recurse=False):
                uses[id(p)] = uses.get(id(p), 0) + 1
        shared = {i for i, n in uses.items() if n > 1}
        for parent in list(module.modules()):
            for name, child in list(parent.named_children()):
                if type(child) is torch.nn.Linear:     # exactly Linear: MultiheadAttention's out_proj must stay as it is
                    parent._modules[name] = int8_linear.from_float(child)
                    if id(child.weight) not in shared:           # a weight another layer still uses stays until the end
                        child.weight.data = torch.empty(0)       # the int8 layer has its own weight and bias
    gc.collect()
    trim_heap()
    return module.eval()


def _int8_linear_class():
    """Int8Linear, made on first use so that importing this module does not import torch (an optional dependency)."""
    cls = globals().get("Int8Linear")
    if cls is not None:
        return cls
    import torch

    class Int8Linear(torch.nn.Module):
        """A Linear whose weight is stored as int8, symmetric per output row (scale = max|row| / 127), with an fp32
        scale per row and an fp32 bias. Each call dequantises the weight for that call only. It does not use torch's
        quantised engines, so its memory and results are the same on every platform."""

        def __init__(self, in_features: int, out_features: int, bias: bool = True):
            super().__init__()
            self.in_features, self.out_features = in_features, out_features
            self.register_buffer("weight", torch.zeros(out_features, in_features, dtype=torch.int8))
            self.register_buffer("scale", torch.ones(out_features))
            self.register_buffer("bias", torch.zeros(out_features) if bias else None)

        @classmethod
        def from_float(cls, linear: torch.nn.Linear) -> "Int8Linear":
            q = cls(linear.in_features, linear.out_features, bias=linear.bias is not None)
            with torch.no_grad():
                w = linear.weight.detach().float()
                top = w.abs().amax(dim=1)
                scale = torch.where(top > 0, top / 127, torch.ones_like(top))      # a row of zeros: any scale, not 0
                q.weight = torch.round(w / scale[:, None]).clamp_(-127, 127).to(torch.int8)
                q.scale = scale
                if linear.bias is not None:
                    q.bias = linear.bias.detach().float().clone()
            return q

        def forward(self, x):
            w = self.weight.to(x.dtype)
            w.mul_(self.scale.to(x.dtype)[:, None])
            return torch.nn.functional.linear(x, w, None if self.bias is None else self.bias.to(x.dtype))

        def extra_repr(self) -> str:
            return f"in_features={self.in_features}, out_features={self.out_features}, bias={self.bias is not None}"

    Int8Linear.__module__, Int8Linear.__qualname__ = __name__, "Int8Linear"     # stored copies pickle it by this name
    globals()["Int8Linear"] = Int8Linear
    return Int8Linear


def __getattr__(name):          # `from shadow.quant import Int8Linear`, and unpickling a stored int8 model
    if name == "Int8Linear":
        return _int8_linear_class()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def int8_wanted(settings: Settings) -> bool:
    return bool(settings.models.int8) and settings.resolved_device() == "cpu"


def total_ram_gb() -> float:
    import psutil
    return psutil.virtual_memory().total / 1e9


def asr_int8(settings: Settings) -> bool:
    """The recogniser is 8-bit when int8 is on, it is not in int8_skip, and the machine has less RAM than
    asr_int8_below_ram_gb (8-bit loses a little accuracy, so a roomy machine keeps fp32)."""
    m = settings.models
    return int8_wanted(settings) and "asr" not in m.int8_skip and total_ram_gb() < m.asr_int8_below_ram_gb


def cpu_threads(settings: Settings) -> int:
    if settings.models.threads > 0:
        return settings.models.threads
    cores = None
    try:
        import psutil
        cores = psutil.cpu_count(logical=False)
    except Exception:
        pass
    return max(1, (cores or os.cpu_count() or 2) - 1)

