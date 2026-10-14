from datetime import datetime, timedelta, timezone
import pytest
from sqlmodel import Session
from shadow.config import DrillCfg
from shadow.drill.focus import auto_focus, focus_label, rank_focuses
from shadow.store.models import Attempt, DrillSession, Lesson, Segment, SyllableScore

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


def _rows(db, rows, *, days_ago=1, seg_text="好"):
    """rows: (ch, pinyin, target_tone, prev_tone, score, status), each on its own attempt of one new segment."""
    les = Lesson(title="L", source_type="upload", status="ready"); db.add(les); db.commit()
    seg = Segment(lesson_id=les.id, idx=0, start_s=0, end_s=1, text=seg_text); db.add(seg); db.commit()
    for ch, py, t, p, score, status in rows:
        a = Attempt(segment_id=seg.id, mode="echo", audio_path="x.wav", duration_s=1.0, created_at=NOW - timedelta(days=days_ago))
        db.add(a); db.commit()
        db.add(SyllableScore(attempt_id=a.id, segment_id=seg.id, idx=0, ch=ch, pinyin_toneless=py, tone=t,
                             target_tone=t, prev_tone=p, tone_score=score, status=status))
    db.commit()


@pytest.fixture
def db(client):
    with Session(client.app.state.engine) as s:
        yield s


def test_labels():
    assert focus_label("tone", "3") == "tone 3 (low)"
    assert focus_label("pair", "3-3") == "tone pair 3→3"
    assert focus_label("char", "在", "zai") == "在 zai" and focus_label("char", "在") == "在"


def test_tone_and_pair_means_missing_counts_zero_unvoiced_ignored(db):
    _rows(db, [("好", "hao", 3, 3, 0.4, "close")] * 6 + [("好", "hao", 3, 3, None, "missing")] * 2
              + [("好", "hao", 3, 3, None, "unvoiced")] * 5)
    f = {(x.kind, x.key): x for x in rank_focuses(db, DrillCfg(), now=NOW)}
    assert f[("tone", "3")].n == 8 and f[("tone", "3")].mean == pytest.approx(0.3)
    assert f[("pair", "3-3")].n == 8


def test_focus_needs_min_rows_and_two_sentences_for_chars(db):
    _rows(db, [("在", "zai", 4, 1, 0.2, "wrong")] * 7)                    # 7 rows: below min_rows
    assert rank_focuses(db, DrillCfg(), now=NOW) == []
    _rows(db, [("在", "zai", 4, 1, 0.2, "wrong")] * 3)                    # 10 rows but one sentence each call…
    keys = {(x.kind, x.key) for x in rank_focuses(db, DrillCfg(), now=NOW)}
    assert ("tone", "4") in keys and ("char", "在") in keys               # …two sentences now (two _rows calls)


def test_window_and_neutral_excluded(db):
    _rows(db, [("的", "de", 0, 1, 0.1, "close")] * 10)                    # neutral: never a focus
    _rows(db, [("是", "shi", 4, 1, 0.1, "close")] * 10, days_ago=40)     # outside the 30-day window
    assert rank_focuses(db, DrillCfg(), now=NOW) == []


def test_weakest_first_and_rotation(db):
    _rows(db, [("好", "hao", 3, 1, 0.30, "close")] * 8)
    _rows(db, [("是", "shi", 4, 2, 0.33, "close")] * 8)
    fs = [f for f in rank_focuses(db, DrillCfg(), now=NOW) if f.kind == "tone"]
    assert [f.key for f in fs] == ["3", "4"]
    assert auto_focus(db, fs, DrillCfg()).key == "3"
    ds = DrillSession(kind="tone", key="3", label="tone 3 (low)", items_json=[], ended_at=NOW); db.add(ds); db.commit()
    assert auto_focus(db, fs, DrillCfg()).key == "3"                      # no takes: not a drill that happened
    db.add(Attempt(segment_id=1, mode="drill", audio_path="x.wav", duration_s=1.0, drill_session_id=ds.id)); db.commit()
    assert auto_focus(db, fs, DrillCfg()).key == "4"                      # last drill was tone 3, tone 4 within 0.05
    db.add(DrillSession(kind="tone", key="4", label="tone 4", items_json=[], ended_at=NOW + timedelta(hours=1))); db.commit()
    assert auto_focus(db, fs, DrillCfg()).key == "4"                      # a later empty drill does not hide it
    assert auto_focus(db, [], DrillCfg()) is None


def test_focuses_endpoint(client, db):
    _rows(db, [("好", "hao", 3, 3, 0.3, "close")] * 8)
    out = client.get("/drill/focuses").json()
    assert out["auto"] is not None and out["focuses"][0]["label"]
