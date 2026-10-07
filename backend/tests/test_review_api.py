from datetime import datetime, timedelta, timezone
from sqlmodel import Session
from shadow.store.models import Attempt, Segment
from tests.test_lessons_api import _upload


def test_unexported_lists_practised_sentences_without_a_note_newest_first(client, tmp_path):
    lid = _upload(client, tmp_path, "L")
    segs = client.get(f"/lessons/{lid}").json()["segments"]
    t0 = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
    with Session(client.app.state.engine) as db:
        for sid, minutes in ((segs[0]["id"], 0), (segs[0]["id"], 5), (segs[2]["id"], 3), (segs[1]["id"], 9)):
            db.add(Attempt(segment_id=sid, mode="flow", audio_path="x.wav", duration_s=1.0, created_at=t0 + timedelta(minutes=minutes)))
        sent = db.get(Segment, segs[1]["id"])
        sent.anki_note_id = 77                                   # in Anki: never listed, however recent
        db.add(sent)
        db.commit()
    out = client.get("/review/unexported").json()
    assert [r["segment"]["id"] for r in out] == [segs[0]["id"], segs[2]["id"]]     # last attempts 09:05, 09:03
    first = out[0]
    assert (first["lesson_id"], first["lesson_title"], first["lesson_source_type"]) == (lid, "L", "upload")
    assert first["segment"]["attempts"] == 2 and first["last_attempt_at"].startswith("2026-10-07T09:05")


def test_unexported_is_empty_without_attempts(client, tmp_path):
    _upload(client, tmp_path)
    assert client.get("/review/unexported").json() == []
