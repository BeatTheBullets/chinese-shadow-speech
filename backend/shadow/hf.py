"""Shared Hugging Face plumbing: one guarded transformers import, and a process-wide model-load lock.

Importing transformers from two threads at once can fail half-way (`cannot import name 'Wav2Vec2CTCTokenizer'`),
and its empty-weights loading patches torch globally while it runs, so a model built in another thread meanwhile gets
meta tensors (`Cannot copy out of meta tensor`). Hence: one import under a lock, and every model class builds its
model under `model_load_lock`. Lock order: a class's own lock is outer, this one inner; hold it only while
constructing a model, never during inference."""
from __future__ import annotations
import threading

model_load_lock = threading.Lock()

_import_lock = threading.Lock()
_classes: tuple[type, type, type] | None = None


def _import() -> tuple[type, type, type]:
    from transformers import Wav2Vec2Model, Wav2Vec2ForCTC, Wav2Vec2CTCTokenizer
    return Wav2Vec2Model, Wav2Vec2ForCTC, Wav2Vec2CTCTokenizer


def wav2vec2_classes() -> tuple[type, type, type]:
    """(Wav2Vec2Model, Wav2Vec2ForCTC, Wav2Vec2CTCTokenizer), imported once."""
    global _classes
    with _import_lock:
        if _classes is None:
            _classes = _import()
        return _classes
