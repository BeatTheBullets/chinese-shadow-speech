import numpy as np
import soundfile as sf
from sqlmodel import Session, select
from shadow.store.models import Attempt, Segment, SyllableScore, VoiceProfile
from tests.helpers import make_tone_wav
from tests.test_lessons_api import _upload


def _post(client, path, sid):
    with open(path, "rb") as f:
        return client.post(f"/segments/{sid}/attempts", files={"audio": ("a.wav", f, "audio/wav")}, data={"mode": "echo"})


def _first_segment(client, tmp_path):
    lid = _upload(client, tmp_path)
    return lid, client.get(f"/lessons/{lid}").json()["segments"][0]


def test_a_take_is_scored_with_rows_and_feeds_the_profile(client, tmp_path):
    lid, seg = _first_segment(client, tmp_path)
    r = _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"])
    assert r.status_code == 201
    sj = r.json()["score_json"]
    assert sj["warnings"] == [] and sj["overall"] is not None and sj["model_version"] == "fake"
    n = len(sj["syllables"])
    assert n == len([s for w in seg["words_json"] for s in w["syllables"]])
    assert sj["ref_contour"]["step_ms"] == 10 and len(sj["usr_contour"]["spans"]) == n
    with Session(client.app.state.engine) as db:
        rows = db.exec(select(SyllableScore).where(SyllableScore.attempt_id == r.json()["id"])).all()
        assert len(rows) == n and {x.status for x in rows} <= {"ok", "close", "wrong", "unvoiced", "missing"}
        prof = db.exec(select(VoiceProfile)).one()
        assert prof.voiced_s > 1.0 and abs(prof.baseline_hz - 220) < 5
    assert client.get(f"/lessons/{lid}").json()["segments"][0]["last_score"] == sj["overall"]


def test_lesson_baseline_is_cached_on_the_lesson(client, tmp_path):
    from shadow.store.models import Lesson
    lid, seg = _first_segment(client, tmp_path)
    _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"])
    with Session(client.app.state.engine) as db:
        pitch = db.get(Lesson, lid).meta_json["pitch"]
        assert abs(pitch["baseline_hz"] - 220) < 5 and pitch["frames"] > 100


def test_gated_take_has_no_rows_and_null_overall(client, tmp_path):
    lid, seg = _first_segment(client, tmp_path)
    silent = tmp_path / "s.wav"
    sf.write(silent, np.zeros(16000 * 2, dtype="float32"), 16000)
    sj = _post(client, silent, seg["id"]).json()["score_json"]
    assert sj["overall"] is None and "too_quiet" in sj["warnings"]
    with Session(client.app.state.engine) as db:
        assert db.exec(select(SyllableScore)).all() == [] and db.exec(select(VoiceProfile)).all() == []


def test_null_overall_is_skipped_by_lessons_and_stats(client, tmp_path):
    lid, seg = _first_segment(client, tmp_path)
    good = _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"]).json()["score_json"]["overall"]
    silent = tmp_path / "s.wav"
    sf.write(silent, np.zeros(16000 * 2, dtype="float32"), 16000)
    _post(client, silent, seg["id"])
    out = client.get(f"/lessons/{lid}").json()["segments"][0]
    assert (out["last_score"], out["best_score"], out["attempts"]) == (good, good, 2)
    assert client.get("/stats/sentences").status_code == 200
    assert client.get(f"/lessons/{lid}/stats").status_code == 200
    assert client.get("/lessons").json()[0]["mean_last_score"] == good


def test_no_reference_alignment(client, tmp_path):
    lid, seg = _first_segment(client, tmp_path)
    with Session(client.app.state.engine) as db:
        s = db.get(Segment, seg["id"]); s.ref_alignment_json = None; db.add(s); db.commit()
    sj = _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"]).json()["score_json"]
    assert sj["warnings"] == ["no_reference"] and sj["overall"] is None


def test_a_scoring_crash_still_saves_the_take(client, tmp_path, monkeypatch):
    import shadow.scoring as scoring
    lid, seg = _first_segment(client, tmp_path)
    monkeypatch.setattr(scoring, "score_take", lambda **kw: 1 / 0)
    r = _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"])
    assert r.status_code == 201 and r.json()["score_json"]["warnings"] == ["score_failed"]
    assert client.get(f"/attempts/{r.json()['id']}/audio").status_code == 200
    with Session(client.app.state.engine) as db:
        assert db.exec(select(Attempt)).one().score_json["overall"] is None


def test_scoring_does_not_hold_the_write_lock(client, tmp_path, monkeypatch):
    """A slow score (first-ever take downloads the embedder) must not lock the database: another write meanwhile
    (the next Echo upload, an ingest job) would wait SQLite's busy timeout, fail, and lose its take."""
    import threading
    from sqlalchemy import create_engine
    import shadow.scoring as scoring
    lid, seg = _first_segment(client, tmp_path)
    started, release, real = threading.Event(), threading.Event(), scoring.score_take

    def slow(**kw):
        started.set(); release.wait(10)
        return real(**kw)
    monkeypatch.setattr(scoring, "score_take", slow)
    out = {}
    t = threading.Thread(target=lambda: out.update(r=_post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"])))
    t.start()
    try:
        assert started.wait(10)
        other = create_engine(client.app.state.engine.url, connect_args={"timeout": 0.5})
        with Session(other) as db:              # fails with "database is locked" while the request holds the lock
            db.add(Attempt(segment_id=seg["id"], mode="echo", audio_path="", duration_s=0.0)); db.commit()
        other.dispose()
    finally:
        release.set(); t.join(10)
    assert out["r"].status_code == 201 and out["r"].json()["score_json"]["overall"] is not None


def test_a_failing_score_write_still_saves_the_take(client, tmp_path, monkeypatch):
    import shadow.scoring as scoring
    lid, seg = _first_segment(client, tmp_path)
    monkeypatch.setattr(scoring, "add_frames", lambda *a: 1 / 0)
    r = _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"])
    assert r.status_code == 201 and r.json()["score_json"]["warnings"] == ["score_failed"]
    assert client.get(f"/attempts/{r.json()['id']}/audio").status_code == 200
    with Session(client.app.state.engine) as db:
        att = db.exec(select(Attempt)).one()
        assert att.audio_path and att.duration_s > 0 and att.score_json["overall"] is None
        assert db.exec(select(SyllableScore)).all() == [] and db.exec(select(VoiceProfile)).all() == []


def test_a_take_of_other_words_is_saved_but_not_scored(client, tmp_path):
    from shadow.ingest.asr import FakeHearer
    client.app.state.deps.hearer = FakeHearer("我是学生。")
    lid, seg = _first_segment(client, tmp_path)
    r = _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"])
    assert r.status_code == 201
    sj = r.json()["score_json"]
    assert sj["warnings"] == ["different_words"] and sj["overall"] is None and sj["heard_text"] == "我是学生。"
    assert client.get(f"/attempts/{r.json()['id']}/audio").status_code == 200
    with Session(client.app.state.engine) as db:
        assert db.exec(select(SyllableScore)).all() == []


def test_a_take_during_an_import_is_scored_without_the_words_check(client, tmp_path, monkeypatch, caplog):
    import logging
    import shadow.ingest.asr as asr_mod
    from shadow.ingest.asr import AsrHearer, ParaformerASR
    monkeypatch.setattr(asr_mod, "HEAR_WAIT_S", 0.01)
    asr = ParaformerASR("none", "cpu")
    client.app.state.deps.hearer = AsrHearer(asr)
    lid, seg = _first_segment(client, tmp_path)
    with asr._lock, caplog.at_level(logging.INFO):                    # an ingest job is transcribing a video
        sj = _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"]).json()["score_json"]
    assert sj["warnings"] == [] and sj["overall"] is not None and sj["heard_text"] is None
    assert "words check skipped" in caplog.text


def test_sound_results_are_stored_on_the_rows(client, tmp_path):
    from shadow.scoring.sounds.detector import FakeSounds
    lid, seg = _first_segment(client, tmp_path)
    n = len([s for w in seg["words_json"] for s in w["syllables"]])
    res = [{"status": "slip", "heard": "zhong", "heard_pinyin": "zhōng", "z": 6.0, "rule": "fused"}] + [None] * (n - 1)
    client.app.state.deps.sounds = FakeSounds(res)
    r = _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"])
    sj = r.json()["score_json"]
    assert sj["sounds_off"] == 1 and sj["sounds_checked"] == 1
    with Session(client.app.state.engine) as db:
        rows = db.exec(select(SyllableScore).where(SyllableScore.attempt_id == r.json()["id"]).order_by(SyllableScore.idx)).all()
    assert rows[0].sound_status == "slip" and rows[0].heard_syllable == "zhong" and rows[0].seg_score == 6.0
    assert rows[1].sound_status is None
