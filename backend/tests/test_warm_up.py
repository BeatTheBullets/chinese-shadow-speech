import threading
import time
from types import SimpleNamespace
from shadow.main import warm_up_in_order, watch_sounds_warm_up
from shadow.scoring.sounds.charctc import CharCtc


def test_warm_up_runs_one_step_at_a_time_in_order():
    log = []

    def step(name):
        def run():
            log.append(("start", name)); time.sleep(0.05); log.append(("end", name))
        return run
    t = threading.Thread(target=warm_up_in_order, args=([step("asr"), step("embedder"), step("chars")],))
    t.start(); t.join(5)
    assert log == [(k, n) for n in ("asr", "embedder", "chars") for k in ("start", "end")]


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
