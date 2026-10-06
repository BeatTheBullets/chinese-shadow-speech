from sqlmodel import Session, select
from shadow.ingest.pipeline import _merge_meta, _set_status
from shadow.store.models import Segment
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
