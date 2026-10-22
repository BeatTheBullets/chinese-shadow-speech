from sqlmodel import Session, select
from shadow.scoring.sounds.backfill import backfill_attempt
from shadow.scoring.sounds.detector import FakeSounds
from shadow.store.models import Attempt, SyllableScore
from tests.helpers import make_tone_wav
from tests.test_scoring_api import _first_segment, _post


def _rows(db, aid):
    return db.exec(select(SyllableScore).where(SyllableScore.attempt_id == aid).order_by(SyllableScore.idx)).all()


def test_backfill_writes_only_sound_fields(client, tmp_path):
    lid, seg = _first_segment(client, tmp_path)
    n = len([s for w in seg["words_json"] for s in w["syllables"]])
    aid = _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"]).json()["id"]
    deps = client.app.state.deps
    assert deps.sounds is None
    res = [{"status": "slip", "heard": "zhong", "heard_pinyin": "zhōng", "z": 6.0, "rule": "fused"}] + [None] * (n - 1)
    deps.sounds = FakeSounds(res)
    with Session(client.app.state.engine) as db:
        before = [(r.tone_score, r.status, r.target_tone) for r in _rows(db, aid)]
        overall = db.get(Attempt, aid).score_json["overall"]
        assert backfill_attempt(deps, db, db.get(Attempt, aid)) is True
        db.commit()
    for _ in range(2):                    # the second pass changes nothing
        with Session(client.app.state.engine) as db:
            rows = _rows(db, aid)
            sj = db.get(Attempt, aid).score_json
            assert [(r.tone_score, r.status, r.target_tone) for r in rows] == before and sj["overall"] == overall
            assert sj["sounds_off"] == 1 and sj["sounds_checked"] == 1 and sj["syllables"][0]["sound"]["heard"] == "zhong"
            assert rows[0].sound_status == "slip" and rows[0].heard_syllable == "zhong" and rows[0].seg_score == 6.0
            assert rows[1].sound_status is None
            backfill_attempt(deps, db, db.get(Attempt, aid)); db.commit()


def test_backfill_skips_unscored_attempts(client, tmp_path):
    lid, seg = _first_segment(client, tmp_path)
    aid = _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"]).json()["id"]
    deps = client.app.state.deps
    deps.sounds = FakeSounds()
    with Session(client.app.state.engine) as db:
        att = db.get(Attempt, aid)
        att.score_json = {**att.score_json, "overall": None}
        assert backfill_attempt(deps, db, att) is False
        assert att.score_json.get("sounds_checked") is None


def test_one_failing_take_does_not_block_the_rest(client, tmp_path):
    from shadow.scoring.sounds.backfill import backfill_all
    lid, seg = _first_segment(client, tmp_path)
    ids = [_post(client, make_tone_wav(tmp_path / f"t{i}.wav", 2.6), seg["id"]).json()["id"] for i in range(2)]
    n = len([s for w in seg["words_json"] for s in w["syllables"]])
    res = [{"status": "slip", "heard": "zhong", "heard_pinyin": "zhōng", "z": 6.0, "rule": "fused"}] + [None] * (n - 1)
    deps = client.app.state.deps
    deps.sounds = FakeSounds(res)
    with Session(client.app.state.engine) as db:
        bad = db.get(Attempt, ids[0])
        bad.score_json = {**bad.score_json, "syllables": [{k: v for k, v in s.items() if k != "status"} for s in bad.score_json["syllables"]]}
        db.add(bad); db.commit()
        counts = backfill_all(deps, db)
    assert counts == {"done": 1, "skipped": 0, "failed": 1, "slips": 1}
    with Session(client.app.state.engine) as db:
        assert db.get(Attempt, ids[0]).score_json.get("sounds_checked") is None
        assert db.get(Attempt, ids[1]).score_json["sounds_checked"] == 1 and _rows(db, ids[1])[0].sound_status == "slip"
        assert _rows(db, ids[0])[0].sound_status is None
