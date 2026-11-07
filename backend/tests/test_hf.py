import sys
import threading
import time
import types

import shadow.hf as hf


def test_wav2vec2_classes_import_once_across_threads(monkeypatch):
    calls = []
    monkeypatch.setattr(hf, "_classes", None)
    monkeypatch.setattr(hf, "_import", lambda: (calls.append(1), ("M", "C", "T"))[1])
    threads = [threading.Thread(target=hf.wav2vec2_classes) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert calls == [1] and hf.wav2vec2_classes() == ("M", "C", "T")


class _Probe:
    """Records whether two constructions ever run at the same time."""
    def __init__(self):
        self.active = 0
        self.max_active = 0
        self._m = threading.Lock()

    def build(self):
        with self._m:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(0.05)
        with self._m:
            self.active -= 1


def test_concurrent_loads_of_different_classes_never_overlap(monkeypatch):
    from shadow.ingest.asr import ParaformerASR
    from shadow.scoring.embed import Wav2Vec2Embedder
    probe = _Probe()

    class FakeAutoModel:
        def __init__(self, **kw):
            probe.build()

    class FakeWav2Vec2Model:
        @classmethod
        def from_pretrained(cls, *a, **kw):
            probe.build()
            return cls()

        def to(self, device): return self
        def eval(self): return self

    monkeypatch.setitem(sys.modules, "funasr", types.SimpleNamespace(AutoModel=FakeAutoModel))
    monkeypatch.setattr("shadow.ingest.asr._local_snapshot", lambda name: name)   # nothing cached
    monkeypatch.setattr(hf, "_classes", (FakeWav2Vec2Model, None, None))
    asr, emb = ParaformerASR("m", "cpu"), Wav2Vec2Embedder("n", "r", 9, "cpu")
    threads = [threading.Thread(target=asr._load), threading.Thread(target=emb._load)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert probe.max_active == 1
    assert asr._model is not None and emb._model is not None


class _NotCached(OSError):
    """Stands in for huggingface_hub's LocalEntryNotFoundError (an OSError) and transformers' "not in the cache"."""


def test_local_first_uses_the_cached_copy_without_the_network():
    calls = []

    def load(name, **kw):
        calls.append(kw)
        return "local"
    assert hf.local_first(load, "n", revision="r") == "local"
    assert calls == [{"revision": "r", "local_files_only": True}]


def test_local_first_downloads_when_the_files_are_not_cached():
    calls = []

    def load(name, **kw):
        calls.append(kw)
        if kw.get("local_files_only"):
            raise _NotCached("not in the cache")
        return "downloaded"
    assert hf.local_first(load, "n", revision="r") == "downloaded"
    assert calls == [{"revision": "r", "local_files_only": True}, {"revision": "r"}]


def test_local_first_does_not_swallow_other_errors():
    import pytest
    calls = []

    def load(name, **kw):
        calls.append(kw)
        raise RuntimeError("broken weights")
    with pytest.raises(RuntimeError, match="broken weights"):
        hf.local_first(load, "n")
    assert len(calls) == 1
