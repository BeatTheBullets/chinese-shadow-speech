import ctypes
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
