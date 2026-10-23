"""8-bit models for a CPU-only laptop: dynamic int8 quantisation of the Linear layers, and the CPU thread budget."""
from __future__ import annotations
import gc
import os
import re
import logging
import warnings
from pathlib import Path
from shadow.config import Settings
from shadow.memory import trim_heap

log = logging.getLogger(__name__)


QUANT_FORMAT = 1          # bump on any change to the quantisation recipe or to what is stored: stored models are rebuilt


def int8_cache_path(key: str) -> Path:
    """Where the quantised model for `key` is kept: <models dir>/int8/, named by the key, QUANT_FORMAT and torch's version.
    The caller puts the versions of the library whose classes are pickled (transformers, torchaudio) in the key."""
    import torch
    from shadow.ingest.punct import models_cache_dir
    return models_cache_dir() / "int8" / (re.sub(r"[^A-Za-z0-9._-]", "_", f"{key}-q{QUANT_FORMAT}-torch{torch.__version__}") + ".pt")


def cached_int8(key: str, build):
    """The quantised module build() returns, kept on disk after the first build: a later load reads the int8 weights
    only (about a quarter of the fp32 size) instead of loading fp32 and quantising, whose peak is 3x higher.
    The whole module is pickled, so the key must name the library versions; an unreadable file is rebuilt."""
    import torch
    path = int8_cache_path(key)
    root = path.parent
    if path.exists():
        try:
            return torch.load(path, map_location="cpu", weights_only=False).eval()
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
    except Exception:
        log.exception("could not store the int8 model %s", path.name)
        tmp.unlink(missing_ok=True)
    return model


def quantize_linear(module):
    """Dynamic qint8 over every torch.nn.Linear (weights stored as int8, activations quantised on the fly); eval mode.
    The fp32 weights are freed once the caller drops its reference."""
    import torch
    # Weights read lazily from a checkpoint stay memory-mapped to its file while any tensor refers to them (the sounds
    # model kept 1.2 GB resident after quantising). So each tensor is copied out of the mapping (the Linear weights one
    # at a time, emptied again once quantised: one fp32 copy at a time) and the mapping goes.
    cfg = torch.ao.quantization.default_dynamic_qconfig
    with warnings.catch_warnings(), torch.no_grad():     # torch 2.11 (pinned) still has it; its torchao pointer is noise
        warnings.filterwarnings("ignore", message=r"torch\.ao\.quantization is deprecated", category=DeprecationWarning)
        for m in module.modules():
            if type(m) is not torch.nn.Linear:
                for t in [*m.parameters(recurse=False), *m.buffers(recurse=False)]:
                    t.data = t.data.clone()
        uses: dict[int, int] = {}
        for m in module.modules():
            if type(m) is torch.nn.Linear:
                uses[id(m.weight)] = uses.get(id(m.weight), 0) + 1
        shared = {i for i, n in uses.items() if n > 1}
        for parent in list(module.modules()):
            for name, child in list(parent.named_children()):
                if type(child) is torch.nn.Linear:     # exactly Linear: MultiheadAttention's out_proj must stay as it is
                    for t in (child.weight, child.bias):
                        if t is not None:
                            t.data = t.data.clone()
                    child.qconfig = cfg
                    parent._modules[name] = torch.ao.nn.quantized.dynamic.Linear.from_float(child)
                    if id(child.weight) not in shared:           # a weight another layer still uses stays until the end
                        child.weight.data = torch.empty(0)       # the quantised layer keeps the bias tensor, not the weight
        q = module
    gc.collect()
    trim_heap()
    return q.eval()


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
