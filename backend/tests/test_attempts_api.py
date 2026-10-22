from sqlmodel import Session, select
from shadow.store.models import Attempt, PracticeSession, SyllableScore
from tests.helpers import make_tone_wav
from tests.test_lessons_api import _upload


def _post(client, tmp_path, sid, **data):
    wav = make_tone_wav(tmp_path / "att.wav", 2.6)       # long enough for the too_short gate: a gated take is dropped
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
    assert att["score_json"] is not None and abs(att["duration_s"] - 2.6) < 0.05
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


def _post_wav(client, path, sid, **data):
    with open(path, "rb") as f:
        return client.post(f"/segments/{sid}/attempts", files={"audio": ("a.wav", f, "audio/wav")}, data={"mode": "echo", **data})


def _silent(tmp_path):
    import numpy as np
    import soundfile as sf
    p = tmp_path / "silent.wav"
    sf.write(p, np.zeros(16000 * 2, dtype="float32"), 16000)
    return p


def test_too_quiet_take_is_dropped(client, tmp_path):
    lid = _upload(client, tmp_path)
    sid = client.get(f"/lessons/{lid}").json()["segments"][0]["id"]
    sess = client.post("/sessions", json={"lesson_id": lid, "mode": "echo"}).json()
    r = _post_wav(client, _silent(tmp_path), sid, session_id=sess["id"])
    assert r.status_code == 200
    body = r.json()
    assert body["dropped"] is True and body["id"] is None
    assert body["score_json"]["warnings"][0] == "too_quiet" and body["score_json"]["overall"] is None
    with Session(client.app.state.engine) as db:
        assert db.exec(select(Attempt)).all() == [] and db.exec(select(SyllableScore)).all() == []
        assert db.get(PracticeSession, sess["id"]).attempts_count == 0
    assert not list((client.app.state.files.data_dir / "attempts").glob("*.wav"))
    assert client.get(f"/segments/{sid}/attempts").json() == []
    assert client.get(f"/lessons/{lid}").json()["segments"][0]["attempts"] == 0


def test_score_failed_take_is_kept(client, tmp_path, monkeypatch):
    import shadow.scoring as scoring
    lid = _upload(client, tmp_path)
    sid = client.get(f"/lessons/{lid}").json()["segments"][0]["id"]
    monkeypatch.setattr(scoring, "score_take", lambda **kw: 1 / 0)
    r = _post_wav(client, make_tone_wav(tmp_path / "t.wav", 2.6), sid)
    assert r.status_code == 201
    assert r.json()["dropped"] is False and r.json()["score_json"]["warnings"] == ["score_failed"]
    with Session(client.app.state.engine) as db:
        assert db.exec(select(Attempt)).one().id == r.json()["id"]
    assert client.app.state.files.attempt_wav(r.json()["id"]).exists()


def test_drop_warnings_are_the_recording_gates():
    from shadow.api.attempts import DROP_WARNINGS
    assert DROP_WARNINGS == {"too_short", "too_quiet", "no_voice", "clipped", "wrong_or_unclear", "different_words", "align_failed"}


def _drop_script():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).parents[1] / "scripts" / "drop_failed_takes.py"
    spec = importlib.util.spec_from_file_location("drop_failed_takes", path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def test_drop_failed_takes_script(client, tmp_path):
    """Old takes stored before the gates dropped them: the script removes those (audio, row, score rows) and keeps
    scored takes and server-side failures; --dry-run only counts."""
    lid = _upload(client, tmp_path)
    sid = client.get(f"/lessons/{lid}").json()["segments"][0]["id"]
    good = _post(client, tmp_path, sid).json()["id"]
    files = client.app.state.files
    made = {}
    with Session(client.app.state.engine) as db:
        for w in ("too_quiet", "different_words", "score_failed", "no_reference"):
            a = Attempt(segment_id=sid, mode="echo", audio_path="", duration_s=1.0, score_json={"overall": None, "warnings": [w]})
            db.add(a); db.commit(); db.refresh(a)
            wav = files.attempt_wav(a.id); wav.write_bytes(b"RIFF"); a.audio_path = str(wav); db.add(a)
            db.add(SyllableScore(attempt_id=a.id, segment_id=sid, idx=0, ch="你", pinyin_toneless="ni", tone=3, status="ok"))
            db.commit(); made[w] = a.id
        undecoded = Attempt(segment_id=sid, mode="echo", audio_path="", duration_s=0.0, score_json=None)
        db.add(undecoded); db.commit(); made["undecoded"] = undecoded.id
    script = _drop_script()
    with Session(client.app.state.engine) as db:
        assert script.drop_failed(db, files, dry_run=True) == {"too_quiet": 1, "different_words": 1}
    with Session(client.app.state.engine) as db:
        assert len(db.exec(select(Attempt)).all()) == 6 and files.attempt_wav(made["too_quiet"]).exists()
        assert script.drop_failed(db, files, dry_run=False) == {"too_quiet": 1, "different_words": 1}
    with Session(client.app.state.engine) as db:
        left = {a.id for a in db.exec(select(Attempt)).all()}
        assert left == {good, made["score_failed"], made["no_reference"], made["undecoded"]}
        assert {s.attempt_id for s in db.exec(select(SyllableScore)).all()} <= left
    assert not files.attempt_wav(made["too_quiet"]).exists() and not files.attempt_wav(made["different_words"]).exists()
    assert files.attempt_wav(made["score_failed"]).exists()
