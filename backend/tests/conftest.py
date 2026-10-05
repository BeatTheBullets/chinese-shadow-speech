import pytest
from pathlib import Path


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    (d / "lessons").mkdir(parents=True)
    (d / "attempts").mkdir()
    (d / "cache").mkdir()
    return d


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
    settings.llm.translate = True
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
