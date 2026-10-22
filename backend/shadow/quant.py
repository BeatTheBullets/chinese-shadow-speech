"""8-bit models for a CPU-only laptop: dynamic int8 quantisation of the Linear layers, and the CPU thread budget."""
from __future__ import annotations
import gc
import os
from shadow.config import Settings
from shadow.memory import trim_heap


def quantize_linear(module):
    """Dynamic qint8 over every torch.nn.Linear (weights stored as int8, activations quantised on the fly); eval mode.
    The fp32 weights are freed once the caller drops its reference."""
    import torch
    q = torch.ao.quantization.quantize_dynamic(module.eval(), {torch.nn.Linear}, dtype=torch.qint8,
                                            inplace=True)
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
