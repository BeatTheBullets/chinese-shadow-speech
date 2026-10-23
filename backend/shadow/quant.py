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


def cached_int8(key: str, build):
    """The quantised module build() returns, kept on disk after the first build: a later load reads the int8 weights
    only (about a quarter of the fp32 size) instead of loading fp32 and quantising, whose peak is 3x higher.
    Stored beside the Hugging Face cache, keyed by model and torch version; an unreadable file is rebuilt."""
    import torch
    root = Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "shadow-int8"
    path = root / (re.sub(r"[^A-Za-z0-9._-]", "_", f"{key}-torch{torch.__version__}") + ".pt")
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
            if not isinstance(m, torch.nn.Linear):
                for t in [*m.parameters(recurse=False), *m.buffers(recurse=False)]:
                    t.data = t.data.clone()
        for parent in list(module.modules()):
            for name, child in list(parent.named_children()):
                if isinstance(child, torch.nn.Linear):
                    for t in (child.weight, child.bias):
                        if t is not None:
                            t.data = t.data.clone()
                    child.qconfig = cfg
                    parent._modules[name] = torch.ao.nn.quantized.dynamic.Linear.from_float(child)
                    child.weight.data = torch.empty(0)          # the quantised layer keeps the bias tensor, not the weight
        q = module
    gc.collect()
    trim_heap()
    return q.eval()


def int8_wanted(settings: Settings) -> bool:
    return bool(settings.models.int8) and settings.resolved_device() == "cpu"


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
