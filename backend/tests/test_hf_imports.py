import sys
import threading
import time
import types

import shadow.hf as hf


def test_library_imports_are_guarded_and_never_overlap(monkeypatch):
    from shadow.ingest.asr import ParaformerASR
    from shadow.ingest.align import Qwen3Aligner
    state = {"active": 0, "max": 0}
    m = threading.Lock()

    def slow(obj):
        with m:
            state["active"] += 1
            state["max"] = max(state["max"], state["active"])
        time.sleep(0.05)                   # stands for the library importing transformers
        with m:
            state["active"] -= 1
        return obj

    class AutoModel:
        def __init__(self, **kw): pass

    class Qwen3ForcedAligner:
        @classmethod
        def from_pretrained(cls, *a, **kw): return cls()

    funasr, qwen = types.ModuleType("funasr"), types.ModuleType("qwen_asr")
    funasr.__getattr__ = lambda name: slow(AutoModel)
    qwen.__getattr__ = lambda name: slow(Qwen3ForcedAligner)
    monkeypatch.setitem(sys.modules, "funasr", funasr)
    monkeypatch.setitem(sys.modules, "qwen_asr", qwen)
    ts = [threading.Thread(target=ParaformerASR("m", "cpu")._load), threading.Thread(target=Qwen3Aligner("cpu")._load),
          threading.Thread(target=lambda: hf.guarded_import(lambda: slow(None)))]
    for t in ts: t.start()
    for t in ts: t.join()
    assert state["max"] == 1 and state["active"] == 0
