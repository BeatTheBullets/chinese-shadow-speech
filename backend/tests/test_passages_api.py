from sqlmodel import Session, select
from shadow.store.models import Attempt, Passage
from tests.conftest import wait_job
from tests.test_lessons_api import _upload


def test_lesson_detail_lists_passages_with_members_and_done(client, tmp_path):
    lid = _upload(client, tmp_path)
    detail = client.get(f"/lessons/{lid}").json()
    ids, end = [s["id"] for s in detail["segments"]], detail["segments"][-1]["end_s"]
    assert detail["passages"] == [{"idx": 0, "title": f"Passage 1 · 00:00–00:{int(end):02d}", "start_s": 0.0,
                                   "end_s": end, "segment_ids": ids, "done": False}]
    tile = client.get("/lessons").json()[0]
    assert (tile["passage_count"], tile["passages_done"]) == (1, 0)
    with Session(client.app.state.engine) as db:
        for sid in ids:
            db.add(Attempt(segment_id=sid, mode="flow", audio_path="x.wav", duration_s=1.0))
        db.commit()
    assert client.get(f"/lessons/{lid}").json()["passages"][0]["done"] is True
    assert client.get("/lessons").json()[0]["passages_done"] == 1


def test_resplit_and_merge_rebuild_passages(client, tmp_path, monkeypatch):
    import shadow.api.segments as segments_api
    calls, real = [], segments_api.rebuild_passages
    monkeypatch.setattr(segments_api, "rebuild_passages", lambda engine, lid: (calls.append(lid), real(engine, lid)))
    lid = _upload(client, tmp_path)
    seg = client.get(f"/lessons/{lid}").json()["segments"][0]
    assert client.post(f"/segments/{seg['id']}/resplit", json={"at_char_index": 7}).status_code == 200
    detail = client.get(f"/lessons/{lid}").json()
    assert len(detail["segments"]) == 4
    assert detail["passages"][0]["segment_ids"] == [s["id"] for s in detail["segments"]]
    assert client.post(f"/segments/{seg['id']}/merge-next").status_code == 200
    detail = client.get(f"/lessons/{lid}").json()
    assert detail["passages"][0]["segment_ids"] == [s["id"] for s in detail["segments"]]
    assert calls == [lid, lid]


def test_text_edit_rebuilds_passages(client, tmp_path, monkeypatch):
    import shadow.api.segments as segments_api
    calls, real = [], segments_api.rebuild_passages
    monkeypatch.setattr(segments_api, "rebuild_passages", lambda engine, lid: (calls.append(lid), real(engine, lid)))
    lid = _upload(client, tmp_path)
    seg = client.get(f"/lessons/{lid}").json()["segments"][0]
    assert client.patch(f"/segments/{seg['id']}", json={"difficulty_flag": True}).status_code == 200
    assert calls == []                                          # no time change, no rebuild
    assert client.patch(f"/segments/{seg['id']}", json={"text": seg["text"] + "好"}).status_code == 200
    assert calls == [lid]


def test_lesson_without_passage_rows_gets_computed_passages(client, tmp_path):
    lid = _upload(client, tmp_path)
    with Session(client.app.state.engine) as db:               # as if ingested before passages existed
        for p in db.exec(select(Passage).where(Passage.lesson_id == lid)).all():
            db.delete(p)
        db.commit()
    detail = client.get(f"/lessons/{lid}").json()
    assert len(detail["passages"]) == 1
    assert detail["passages"][0]["segment_ids"] == [s["id"] for s in detail["segments"]]
    assert client.get("/lessons").json()[0]["passage_count"] == 1


def test_anki_import_builds_passages(client, tmp_path):
    from tests.test_anki_import import _b64, _dict
    b64 = _b64(tmp_path, seconds=2.0)
    notes = [_dict(1, "你好世界。", "v.mp4 00:00:01.000", b64), _dict(2, "再见。", "v.mp4 00:00:05.000", b64)]
    job = client.post("/lessons/anki", json={"query_name": "q", "notes": notes}).json()["jobs"][0]
    assert wait_job(client, job["job_id"])["status"] == "done"
    with Session(client.app.state.engine) as db:
        rows = db.exec(select(Passage).where(Passage.lesson_id == job["lesson_id"])).all()
    assert len(rows) == 1 and rows[0].title.startswith("Passage 1 · 00:00–")


def test_deleting_a_lesson_deletes_its_passages(client, tmp_path):
    lid = _upload(client, tmp_path)
    assert client.delete(f"/lessons/{lid}").status_code == 204
    with Session(client.app.state.engine) as db:
        assert db.exec(select(Passage).where(Passage.lesson_id == lid)).all() == []
