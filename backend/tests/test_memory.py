import ctypes
from types import SimpleNamespace
from shadow import memory
from tests.conftest import wait_job
from tests.test_attempts_api import _post
from tests.test_lessons_api import _upload


def test_trim_heap_never_raises(monkeypatch):
    memory._libc = None
    assert memory.trim_heap() is None

    def nope(*a, **k):
        raise OSError("no glibc")
    monkeypatch.setattr(ctypes, "CDLL", nope)
    memory._libc = None
    assert memory.trim_heap() is None
    memory._libc = None


def test_jobs_trim_after_each_job(client, monkeypatch):
    calls = []
    monkeypatch.setattr("shadow.jobs.trim_heap", lambda: calls.append(1))

    def boom(progress):
        raise RuntimeError("x")

    ok = client.app.state.jobs.submit(lambda progress: None, None)
    assert wait_job(client, ok)["status"] == "done"
    bad = client.app.state.jobs.submit(boom, None)
    assert wait_job(client, bad)["status"] == "error"
    assert len(calls) == 2


def test_attempt_scoring_trims(client, tmp_path, monkeypatch):
    lid = _upload(client, tmp_path)
    sid = client.get(f"/lessons/{lid}").json()["segments"][0]["id"]
    calls = []
    monkeypatch.setattr("shadow.api.attempts.trim_heap", lambda: calls.append(1))
    assert _post(client, tmp_path, sid).status_code == 201
    assert calls == [1]


def test_release_freed_memory_eagerly_sets_both_thresholds(monkeypatch):
    calls = []
    memory._libc = SimpleNamespace(mallopt=lambda opt, val: calls.append((opt, val)) or 1)
    try:
        assert memory.release_freed_memory_eagerly() is None
    finally:
        memory._libc = None
    assert calls == [(-3, 131072), (-1, 131072)]


def test_release_freed_memory_eagerly_never_raises(monkeypatch):
    def nope(*a, **k):
        raise OSError("no glibc")
    monkeypatch.setattr(ctypes, "CDLL", nope)
    memory._libc = None
    assert memory.release_freed_memory_eagerly() is None
    memory._libc = None
    assert memory.release_freed_memory_eagerly() is None
