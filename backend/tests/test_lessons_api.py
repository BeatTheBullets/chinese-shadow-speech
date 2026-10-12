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
    from shadow.store.models import Segment
    with Session(engine) as db:
        for status in ("queued", "processing", "ready", "error"):
            db.add(Lesson(title=status, source_type="upload", status=status, error="boom" if status == "error" else None))
        # a rebuild or an Anki update interrupted: the lesson already has (consistent) segments, so it stays usable
        busy = Lesson(title="processing with segments", source_type="anki", status="processing")
        db.add(busy); db.commit(); db.refresh(busy)
        db.add(Segment(lesson_id=busy.id, idx=0, start_s=0, end_s=1, text="你好")); db.commit()
    settings = Settings(data_dir=data_dir)
    with TestClient(create_app(settings, deps=fake_deps(settings, fake_transcript))) as c:
        got = {l["title"]: (l["status"], l["error"]) for l in c.get("/lessons").json()}
    msg = "interrupted — the server restarted during processing; delete and re-upload"
    assert got == {"queued": ("error", msg), "processing": ("error", msg), "ready": ("ready", None), "error": ("error", "boom"),
                   "processing with segments": ("ready", None)}


def _lesson_with_scored_attempts(engine) -> tuple[int, list[int]]:
    """Four sentences: attempts inserted out of time order, unscored ones, and a created_at tie broken by id."""
    from datetime import datetime, timedelta, timezone
    from shadow.store.models import Attempt, Lesson
    t0 = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
    with Session(engine) as db:
        lesson = Lesson(title="Scores", source_type="upload", status="ready")
        db.add(lesson); db.flush()
        segs = [Segment(lesson_id=lesson.id, idx=k, start_s=2.0 * k, end_s=2.0 * k + 2, text="我今天想学中文") for k in range(4)]
        db.add_all(segs); db.flush()
        s0, s1, s2, _ = (s.id for s in segs)
        for sid, minutes, score in ((s0, 2, 70.0), (s0, 1, 90.0), (s0, 3, None), (s1, 5, 40.0), (s1, 5, 60.0), (s2, 4, None)):
            db.add(Attempt(segment_id=sid, mode="echo", audio_path="x.wav", duration_s=1.0, created_at=t0 + timedelta(minutes=minutes),
                           score_json=None if score is None else {"overall": score}))
        db.commit()
        return lesson.id, [s.id for s in segs]


def test_attempt_stats_per_sentence_and_lesson(client):
    lid, ids = _lesson_with_scored_attempts(client.app.state.engine)
    want = [(3, 70.0, 90.0), (2, 60.0, 60.0), (1, None, None), (0, None, None)]   # (attempts, last, best)
    stats = lambda s: (s["attempts"], s["last_score"], s["best_score"])
    detail = client.get(f"/lessons/{lid}").json()
    assert [stats(s) for s in detail["segments"]] == want
    assert (detail["practised_count"], detail["mean_last_score"], detail["segment_count"]) == (3, 65.0, 4)
    listed = next(l for l in client.get("/lessons").json() if l["id"] == lid)
    assert (listed["practised_count"], listed["mean_last_score"], listed["segment_count"]) == (3, 65.0, 4)
    assert listed["passage_count"] == detail["passage_count"] and listed["passages_done"] == detail["passages_done"]
    unexported = client.get("/review/unexported").json()
    assert [(r["segment"]["id"], stats(r["segment"])) for r in unexported] == [(ids[1], want[1]), (ids[2], want[2]), (ids[0], want[0])]
    assert stats(client.patch(f"/segments/{ids[0]}", json={"difficulty_flag": True}).json()) == want[0]


def _add_sentences(engine, lesson_ids: list[int], n: int) -> None:
    from shadow.store.models import Attempt
    with Session(engine) as db:
        for lid in lesson_ids:
            first = len(db.exec(select(Segment).where(Segment.lesson_id == lid)).all())
            segs = [Segment(lesson_id=lid, idx=first + k, start_s=100.0 + 2 * k, end_s=102.0 + 2 * k, text="我今天想学中文") for k in range(n)]
            db.add_all(segs); db.flush()
            db.add_all(Attempt(segment_id=s.id, mode="flow", audio_path="x.wav", duration_s=1.0, score_json={"overall": 50.0}) for s in segs)
        db.commit()


def _statements(engine, call) -> int:
    from sqlalchemy import event
    n = 0

    def count(*_):
        nonlocal n
        n += 1
    event.listen(engine, "before_cursor_execute", count)
    try:
        call()
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return n


def test_the_number_of_queries_does_not_grow_with_the_number_of_sentences(client):
    engine = client.app.state.engine
    lids = [_lesson_with_scored_attempts(engine)[0] for _ in range(3)]
    requests = {"list": lambda: client.get("/lessons").json(), "detail": lambda: client.get(f"/lessons/{lids[0]}").json(),
                "unexported": lambda: client.get("/review/unexported").json()}
    before = {k: _statements(engine, r) for k, r in requests.items()}
    _add_sentences(engine, lids, 20)
    after = {k: _statements(engine, r) for k, r in requests.items()}
    assert after == before
