from __future__ import annotations
import ctypes

_libc = None


def trim_heap() -> None:
    """Models load on the CPU and move to the GPU, and glibc keeps the freed heap (about 2 GB after Paraformer);
    malloc_trim hands it back. A no-op without glibc; never raises."""
    global _libc
    try:
        if _libc is None:
            _libc = ctypes.CDLL("libc.so.6")
        _libc.malloc_trim(0)
    except (OSError, AttributeError):
        pass
