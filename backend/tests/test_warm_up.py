import threading
import time
from types import SimpleNamespace

from shadow.main import start_warm_ups, warm_up_in_order, warm_up_steps, watch_sounds_warm_up
from shadow.scoring.sounds.charctc import CharCtc


class FakeModel:
    """Has a blocking warm() like the real model classes; records enter/exit of its 'load'."""
    def __init__(self, name, log):
        self.name, self.log = name, log

    def warm(self):
        self.log.append(("enter", self.name))
        time.sleep(0.03)
        self.log.append(("exit", self.name))


def _deps(log):
    return SimpleNamespace(asr=FakeModel("asr", log), embedder=FakeModel("embedder", log),
                           sounds=SimpleNamespace(chars=FakeModel("chars", log)))


def test_cpu_warms_only_the_recogniser():
    log = []
    deps = _deps(log)
    assert len(warm_up_steps(deps, "cpu")) == 1
    start_warm_ups(deps, "cpu").join(5)
    assert log == [("enter", "asr"), ("exit", "asr")]


def test_cuda_warms_recogniser_embedder_sounds_one_at_a_time_in_order():
    log = []
    deps = _deps(log)
    assert len(warm_up_steps(deps, "cuda")) == 3
    start_warm_ups(deps, "cuda").join(5)
    assert log == [(e, n) for n in ("asr", "embedder", "chars") for e in ("enter", "exit")]   # never two in flight


def test_models_without_warm_are_skipped():
    deps = SimpleNamespace(asr=object(), embedder=None, sounds=None)
    assert warm_up_steps(deps, "cuda") == []
    start_warm_ups(deps, "cuda").join(5)


def test_a_failing_step_does_not_stop_the_next_one():
    ran = []

    def boom():
        raise OSError("offline")
    warm_up_in_order([boom, lambda: ran.append("embedder")])
    assert ran == ["embedder"]


def test_a_failing_char_ctc_step_switches_sounds_off(monkeypatch):
    chars = CharCtc.__new__(CharCtc)
    chars._lock = threading.Lock(); chars._model = None; chars.load_error = None; chars.name = "x"

    def load():
        raise ImportError("cannot import name 'Wav2Vec2CTCTokenizer'")
    monkeypatch.setattr(chars, "_load", load)
    deps = SimpleNamespace(sounds=SimpleNamespace(chars=chars), sounds_error=None)
    warm_up_in_order([chars.warm])
    t = threading.Thread(target=lambda: None); t.start()
    watch_sounds_warm_up(deps, t)
    assert deps.sounds is None and "Wav2Vec2CTCTokenizer" in deps.sounds_error
