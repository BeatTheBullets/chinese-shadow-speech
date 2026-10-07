from sqlmodel import Session, select
from shadow.ingest.pipeline import _merge_meta, _set_status
from shadow.store.models import Passage, Segment
from tests.helpers import make_tone_wav
from tests.conftest import wait_job


def _upload(client, tmp_path, title="L"):
    wav = make_tone_wav(tmp_path / f"{title}.wav", 8.0)
    with open(wav, "rb") as f:
        r = client.post("/lessons", files={"file": (f"{title}.wav", f, "audio/wav")}, data={"title": title, "speaker": "S"})
    wait_job(client, r.json()["job_id"])
    return r.json()["lesson_id"]


def test_list_get_patch_delete(client, tmp_path):
    lid = _upload(client, tmp_path)
    lst = client.get("/lessons").json()
    assert lst[0]["id"] == lid and lst[0]["segment_count"] == 3 and lst[0]["status"] == "ready"
    detail = client.get(f"/lessons/{lid}").json()
    assert len(detail["segments"]) == 3 and detail["segments"][0]["words_json"]
    assert client.patch(f"/lessons/{lid}", json={"speaker": "李子柒"}).json()["speaker"] == "李子柒"
    assert client.delete(f"/lessons/{lid}").status_code == 204
    assert client.get(f"/lessons/{lid}").status_code == 404
    assert not client.app.state.files.lesson_dir(lid).exists()


def test_list_is_newest_first_and_detail_is_in_idx_order(client, tmp_path):
    a = _upload(client, tmp_path, "A")
    b = _upload(client, tmp_path, "B")
    lst = client.get("/lessons").json()
    assert [l["id"] for l in lst] == [b, a]
    assert lst[0]["practised_count"] == 0 and lst[0]["mean_last_score"] is None
    assert "meta_json" not in lst[0] and "transcript_json" not in lst[0]
    segs = client.get(f"/lessons/{a}").json()["segments"]
    assert [s["idx"] for s in segs] == [0, 1, 2] and all(s["attempts"] == 0 for s in segs)


def test_patch_title_keeps_speaker(client, tmp_path):
    lid = _upload(client, tmp_path)
    out = client.patch(f"/lessons/{lid}", json={"title": "新标题"}).json()
    assert (out["title"], out["speaker"]) == ("新标题", "S")


def test_missing_lesson_is_404(client):
    assert client.get("/lessons/999").status_code == 404
    assert client.patch("/lessons/999", json={"title": "x"}).status_code == 404
    assert client.delete("/lessons/999").status_code == 404


def test_delete_removes_segment_rows(client, tmp_path):
    lid = _upload(client, tmp_path)
    keep = _upload(client, tmp_path, "K")
    assert client.delete(f"/lessons/{lid}").status_code == 204
    with Session(client.app.state.engine) as db:
        assert db.exec(select(Segment).where(Segment.lesson_id == lid)).all() == []
        assert len(db.exec(select(Segment).where(Segment.lesson_id == keep)).all()) == 3


def test_delete_removes_the_lessons_passages(client, tmp_path):
    lid = _upload(client, tmp_path)
    keep = _upload(client, tmp_path, "K")
    with Session(client.app.state.engine) as db:
        for lesson_id in (lid, keep):
            db.add(Passage(lesson_id=lesson_id, idx=0, title="p", start_s=0.0, end_s=1.0))
        db.commit()
    assert client.delete(f"/lessons/{lid}").status_code == 204
    with Session(client.app.state.engine) as db:
        assert db.exec(select(Passage).where(Passage.lesson_id == lid)).all() == []
        assert [r.title for r in db.exec(select(Passage).where(Passage.lesson_id == keep, Passage.title == "p")).all()] == ["p"]    # ingest also built its own


def test_status_helpers_tolerate_a_deleted_lesson(client):
    """A lesson deleted while its ingest job runs must not crash the job's status bookkeeping."""
    engine = client.app.state.engine
    _set_status(engine, 999, "ready", duration_s=1.0)
    _merge_meta(engine, 999, translation_error="x")


def test_delete_removes_attempts_and_list_reports_scores(client, tmp_path):
    from shadow.store.models import Attempt
    lid = _upload(client, tmp_path)
    segs = client.get(f"/lessons/{lid}").json()["segments"]
    with Session(client.app.state.engine) as db:
        for sid, score in ((segs[0]["id"], 60.0), (segs[0]["id"], 80.0), (segs[1]["id"], 50.0)):
            db.add(Attempt(segment_id=sid, mode="echo", audio_path="x.wav", duration_s=1.0, score_json={"overall": score}))
        db.commit()
    out = client.get("/lessons").json()[0]
    assert out["practised_count"] == 2 and out["mean_last_score"] == 65.0
    seg0 = client.get(f"/lessons/{lid}").json()["segments"][0]
    assert (seg0["attempts"], seg0["last_score"], seg0["best_score"]) == (2, 80.0, 80.0)
    assert client.delete(f"/lessons/{lid}").status_code == 204
    with Session(client.app.state.engine) as db:
        assert db.exec(select(Attempt)).all() == []


def test_patch_simplifies_title_and_speaker(client, tmp_path):
    lid = _upload(client, tmp_path)
    out = client.patch(f"/lessons/{lid}", json={"title": "學習中文", "speaker": "李子柒頻道"}).json()
    assert (out["title"], out["speaker"]) == ("学习中文", "李子柒频道")


def test_lesson_ids_are_not_reused_after_deleting_the_newest(client, tmp_path):
    """SQLite reuses max(id)+1 without AUTOINCREMENT: a new lesson would inherit the deleted one's cached clip
    URLs (/segments/{id}/audio), its text prefs and its export filenames."""
    a = _upload(client, tmp_path, "A")
    b = _upload(client, tmp_path, "B")
    old_seg_ids = {s["id"] for s in client.get(f"/lessons/{b}").json()["segments"]}
    assert client.delete(f"/lessons/{b}").status_code == 204
    c = _upload(client, tmp_path, "C")
    assert c > b > a
    assert min(s["id"] for s in client.get(f"/lessons/{c}").json()["segments"]) > max(old_seg_ids)


def test_every_table_with_deletable_rows_uses_autoincrement(client):
    from sqlalchemy import text
    with client.app.state.engine.connect() as conn:
        ddl = dict(conn.execute(text("select name, sql from sqlite_master where type='table'")).all())
    for table in ("lesson", "segment", "attempt", "session", "syllablescore", "passage"):
        assert "AUTOINCREMENT" in ddl[table], table


def test_startup_marks_interrupted_ingests_as_error(data_dir, fake_transcript):
    """A restart (uvicorn --reload, Ctrl-C, WSL shutdown) kills any running job; its lesson must not stay
    queued/processing forever."""
    from fastapi.testclient import TestClient
    from shadow.config import Settings
    from shadow.deps import fake_deps
    from shadow.main import create_app
    from shadow.store.db import init_db, make_engine
    from shadow.store.models import Lesson
    engine = make_engine(data_dir)
    init_db(engine)
    with Session(engine) as db:
        for status in ("queued", "processing", "ready", "error"):
            db.add(Lesson(title=status, source_type="upload", status=status, error="boom" if status == "error" else None))
        db.commit()
    settings = Settings(data_dir=data_dir)
    with TestClient(create_app(settings, deps=fake_deps(settings, fake_transcript))) as c:
        got = {l["title"]: (l["status"], l["error"]) for l in c.get("/lessons").json()}
    msg = "interrupted — the server restarted during processing; delete and re-upload"
    assert got == {"queued": ("error", msg), "processing": ("error", msg), "ready": ("ready", None), "error": ("error", "boom")}
