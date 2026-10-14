from sqlmodel import Session, select
from shadow.store.models import Attempt, PracticeSession, SyllableScore
from tests.helpers import make_tone_wav
from tests.test_lessons_api import _upload


def _post(client, tmp_path, sid, **data):
    wav = make_tone_wav(tmp_path / "att.wav", 1.2)
    with open(wav, "rb") as f:
        return client.post(f"/segments/{sid}/attempts", files={"audio": ("att.wav", f, "audio/wav")},
                           data={"mode": "echo", **data})


def test_session_and_attempt_flow(client, tmp_path):
    lid = _upload(client, tmp_path)
    sid = client.get(f"/lessons/{lid}").json()["segments"][0]["id"]
    sess = client.post("/sessions", json={"lesson_id": lid, "mode": "echo"}).json()
    assert sess["attempts_count"] == 0
    r = _post(client, tmp_path, sid, session_id=sess["id"])
    assert r.status_code == 201
    att = r.json()
    assert att["score_json"] is not None and abs(att["duration_s"] - 1.2) < 0.05
    assert client.get(f"/attempts/{att['id']}/audio").headers["content-type"].startswith("audio/wav")
    hist = client.get(f"/segments/{sid}/attempts").json()
    assert [a["id"] for a in hist] == [att["id"]]
    ended = client.patch(f"/sessions/{sess['id']}", json={"ended": True}).json()
    assert ended["ended_at"] is not None and ended["attempts_count"] == 1
    assert client.get(f"/lessons/{lid}").json()["practised_count"] == 1


def test_bad_audio_rejected(client, tmp_path):
    lid = _upload(client, tmp_path)
    sid = client.get(f"/lessons/{lid}").json()["segments"][0]["id"]
    r = client.post(f"/segments/{sid}/attempts", files={"audio": ("x.wav", b"not audio", "audio/wav")}, data={"mode": "echo"})
    assert r.status_code == 400 and "decoded" in r.json()["detail"]
    with Session(client.app.state.engine) as db:
        assert db.exec(select(Attempt)).all() == []
    assert not list((client.app.state.files.data_dir / "attempts").glob("*.wav"))


def test_attempt_and_session_validation(client, tmp_path):
    lid = _upload(client, tmp_path)
    sid = client.get(f"/lessons/{lid}").json()["segments"][0]["id"]
    assert _post(client, tmp_path, 9999).status_code == 404
    assert _post(client, tmp_path, sid, session_id=9999).status_code == 404
    assert _post(client, tmp_path, sid, mode="nope").status_code == 400
    assert client.post("/sessions", json={"lesson_id": 9999, "mode": "echo"}).status_code == 404
    assert client.post("/sessions", json={"lesson_id": lid, "mode": "nope"}).status_code == 400
    assert client.patch("/sessions/9999", json={"ended": True}).status_code == 404
    assert client.get("/attempts/9999/audio").status_code == 404


def test_attempts_listed_newest_first(client, tmp_path):
    lid = _upload(client, tmp_path)
    sid = client.get(f"/lessons/{lid}").json()["segments"][0]["id"]
    ids = [_post(client, tmp_path, sid).json()["id"] for _ in range(3)]
    assert [a["id"] for a in client.get(f"/segments/{sid}/attempts").json()] == ids[::-1]


def test_lesson_delete_removes_sessions_scores_and_attempt_files(client, tmp_path):
    lid = _upload(client, tmp_path)
    sid = client.get(f"/lessons/{lid}").json()["segments"][0]["id"]
    sess = client.post("/sessions", json={"lesson_id": lid, "mode": "echo"}).json()
    att = _post(client, tmp_path, sid, session_id=sess["id"]).json()
    wav = client.app.state.files.attempt_wav(att["id"])
    assert wav.exists()
    with Session(client.app.state.engine) as db:
        db.add(SyllableScore(attempt_id=att["id"], segment_id=sid, idx=0, ch="你", pinyin_toneless="ni", tone=3, status="ok"))
        db.commit()
    assert client.delete(f"/lessons/{lid}").status_code == 204
    assert not wav.exists()
    with Session(client.app.state.engine) as db:
        for model in (Attempt, PracticeSession, SyllableScore):
            assert db.exec(select(model)).all() == []
