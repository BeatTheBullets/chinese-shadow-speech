import importlib.util
from pathlib import Path
from sqlmodel import Session
from shadow.ingest.asr import FakeHearer
from tests.test_lessons_api import _upload


def _script():
    path = Path(__file__).parents[1] / "scripts" / "clipcheck.py"
    spec = importlib.util.spec_from_file_location("clipcheck", path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def test_clipcheck_compares_each_clip_with_its_sentence(client, tmp_path):
    clipcheck = _script()
    lid = _upload(client, tmp_path)
    with Session(client.app.state.engine) as db:
        rows = clipcheck.check_lesson(db, FakeHearer("其实方法有很多。"), lid)
        assert [round(sim, 2) for _, _, sim in rows][1] == 1.0 and len(rows) == 3
        out = clipcheck.report("lesson", rows)
    assert out.count("sim=") == 2 and out.splitlines()[-1].startswith("lesson: n=3 matched=1 (sim >= 0.8) mean=")
