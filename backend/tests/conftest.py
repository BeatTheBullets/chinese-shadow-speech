import os
import shutil
import uuid
import pytest
from pathlib import Path


@pytest.fixture
def data_dir(tmp_path: Path):
    # SHADOW_TEST_TMP lets CI put data dirs under a path with a space and a non-ASCII letter.
    base = os.environ.get("SHADOW_TEST_TMP")
    root = Path(base) / f"shadow-{uuid.uuid4().hex[:12]}" if base else tmp_path
    d = root / "data"
    (d / "lessons").mkdir(parents=True)
    (d / "attempts").mkdir()
    (d / "cache").mkdir()
    yield d
    if base:
        shutil.rmtree(root, ignore_errors=True)


from fastapi.testclient import TestClient
from shadow.config import Settings
from shadow.deps import fake_deps
from shadow.ingest.text import Cue
from shadow.ingest.transcript import transcript_from_cues
from shadow.main import create_app

LESSON_TEXT = [
    (0.0, 3.0, "我今天想跟你们聊一聊学中文的方法。"),
    (3.0, 5.0, "其实方法有很多。"),
    (5.0, 7.5, "但是最重要的是坚持。"),
]


@pytest.fixture
def fake_transcript():
    return transcript_from_cues([Cue(a, b, t) for a, b, t in LESSON_TEXT])


@pytest.fixture
def client(data_dir, fake_transcript):
    settings = Settings(data_dir=data_dir)
    app = create_app(settings, deps=fake_deps(settings, fake_transcript))
    with TestClient(app) as c:
        yield c


def wait_job(client, job_id, timeout=10.0):
    import time
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = client.get(f"/jobs/{job_id}").json()
        if j["status"] in ("done", "error"):
            return j
        time.sleep(0.05)
    raise AssertionError("job did not finish")


@pytest.fixture(autouse=True)
def _fresh_int8_records(monkeypatch):
    """shadow.quant keeps per-process records of the int8 copies it stored or failed to store (prepare reads them);
    each test starts with empty ones so a failure provoked in one test cannot fail another's prepare."""
    import shadow.quant as quant
    monkeypatch.setattr(quant, "_stored", set())
    monkeypatch.setattr(quant, "_unsaved", set())
