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


def release_freed_memory_eagerly() -> None:
    """In-process equivalent of MALLOC_MMAP_THRESHOLD_ / MALLOC_TRIM_THRESHOLD_ = 131072: glibc returns freed model
    memory at once, not after the load. Measured with FunASR's old ct-punc model (since replaced by the small sherpa-onnx one): the combined Paraformer+VAD+punctuation load peaked at ~6 GB (OOM
    kill) and now peaks at 4.4 GB, 1.2 GB after. Call before any model loads. A no-op without glibc; never raises."""
    global _libc
    try:
        if _libc is None:
            _libc = ctypes.CDLL("libc.so.6")
        _libc.mallopt(-3, 131072)       # M_MMAP_THRESHOLD: big blocks come from mmap and go back on free
        _libc.mallopt(-1, 131072)       # M_TRIM_THRESHOLD: the heap top is trimmed as soon as it frees
    except (OSError, AttributeError):
        pass
