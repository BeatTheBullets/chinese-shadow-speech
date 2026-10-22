import threading
import time
from types import SimpleNamespace

from shadow.main import start_warm_ups, warm_up_steps


class FakeModel:
    """Has warm_up() like the real model classes: starts a thread that records enter/exit of its 'load'."""
    def __init__(self, name, log):
        self.name, self.log = name, log

    def warm_up(self):
        def run():
            self.log.append(("enter", self.name))
            time.sleep(0.03)
            self.log.append(("exit", self.name))
        t = threading.Thread(target=run, daemon=True)
        t.start()
        return t


def _deps(log):
    return SimpleNamespace(asr=FakeModel("asr", log), embedder=FakeModel("embedder", log),
                           sounds=SimpleNamespace(chars=FakeModel("chars", log)))


def test_cpu_warms_only_the_recogniser():
    log = []
    deps = _deps(log)
    assert len(warm_up_steps(deps, "cpu")) == 1
    start_warm_ups(deps, "cpu").join(5)
    assert log == [("enter", "asr"), ("exit", "asr")]


def test_cuda_warms_recogniser_embedder_sounds_in_order():
    log = []
    deps = _deps(log)
    assert len(warm_up_steps(deps, "cuda")) == 3
    start_warm_ups(deps, "cuda").join(5)
    assert [n for e, n in log if e == "enter"] == ["asr", "embedder", "chars"]


def test_steps_run_one_at_a_time():
    log = []
    start_warm_ups(_deps(log), "cuda").join(5)
    assert [e for e, _ in log] == ["enter", "exit"] * 3          # never two loads in flight


def test_models_without_warm_up_are_skipped():
    deps = SimpleNamespace(asr=object(), embedder=None, sounds=None)
    assert warm_up_steps(deps, "cuda") == []
    start_warm_ups(deps, "cuda").join(5)
