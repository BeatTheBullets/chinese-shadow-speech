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


def test_backfill_reuses_the_letter_emissions_of_its_alignment(client, tmp_path):
    from shadow.ingest.align import FakeAligner, LetterEmissions
    from shadow.scoring.sounds.backfill import plan_backfill

    class EmittingAligner(FakeAligner):
        def align_emissions(self, wav, sr, text):
            self.em = LetterEmissions("E", 0.02, self)
            return self.align(wav, sr, text), self.em

    class Spy(FakeSounds):
        def check(self, **kw):
            self.kw = kw
            return super().check(**kw)
    lid, seg = _first_segment(client, tmp_path)
    aid = _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"]).json()["id"]
    deps = client.app.state.deps
    deps.aligner, deps.sounds = EmittingAligner(), Spy()
    with Session(client.app.state.engine) as db:
        assert plan_backfill(deps, db, db.get(Attempt, aid)) is not None
    assert deps.sounds.kw["letter_emissions"] is deps.aligner.em


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


def test_dry_run_writes_nothing(client, tmp_path):
    from shadow.scoring.sounds.backfill import backfill_all
    lid, seg = _first_segment(client, tmp_path)
    ids = [_post(client, make_tone_wav(tmp_path / f"t{i}.wav", 2.6), seg["id"]).json()["id"] for i in range(2)]
    n = len([s for w in seg["words_json"] for s in w["syllables"]])
    res = [{"status": "slip", "heard": "zhong", "heard_pinyin": "zhōng", "z": 6.0, "rule": "fused"}] + [None] * (n - 1)
    deps = client.app.state.deps
    deps.sounds = FakeSounds(res)
    with Session(client.app.state.engine) as db:
        counts = backfill_all(deps, db, dry_run=True, every=1)
    assert counts == {"done": 2, "skipped": 0, "failed": 0, "slips": 2}
    with Session(client.app.state.engine) as db:
        for aid in ids:
            assert db.get(Attempt, aid).score_json.get("sounds_checked") is None
            assert all(r.sound_status is None and r.heard_syllable is None and r.seg_score is None for r in _rows(db, aid))


def _backfill_script():
    import importlib.util
    from pathlib import Path
    path = Path(__file__).parents[1] / "scripts" / "backfill_sounds.py"
    spec = importlib.util.spec_from_file_location("backfill_sounds", path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


def test_backfill_script_dry_run_is_read_only(tmp_path, monkeypatch):
    import sys
    from types import SimpleNamespace
    import pytest
    from shadow.store.db import init_db, make_engine
    mod = _backfill_script()
    monkeypatch.setattr(mod, "build_deps", lambda settings: SimpleNamespace(sounds=FakeSounds(), sounds_error=None))
    # no database: a clean exit, and nothing is created
    monkeypatch.setattr(sys, "argv", ["backfill_sounds.py", "--data-dir", str(tmp_path / "none"), "--dry-run"])
    with pytest.raises(SystemExit, match="no database at"):
        mod.main()
    assert not (tmp_path / "none").exists()
    # a database: opened read-only, and no schema upgrade (init_db would write)
    init_db(make_engine(tmp_path))
    seen = {}

    def fake_backfill_all(deps, db, *, dry_run, every, after_commit):
        seen["url"], seen["dry_run"] = str(db.get_bind().url), dry_run
        return {"done": 0, "skipped": 0, "failed": 0, "slips": 0}
    monkeypatch.setattr(mod, "backfill_all", fake_backfill_all)
    monkeypatch.setattr(mod, "init_db", lambda engine: pytest.fail("init_db on a dry run"))
    monkeypatch.setattr(sys, "argv", ["backfill_sounds.py", "--data-dir", str(tmp_path), "--dry-run"])
    mod.main()
    assert seen["dry_run"] is True and "mode=ro" in seen["url"]
