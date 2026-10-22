from tests.helpers import make_tone_wav
from tests.test_lessons_api import _upload


def test_stats_shapes(client, tmp_path, monkeypatch):
    import shadow.scoring as scoring
    monkeypatch.setattr(scoring, "score_take", lambda **kw: 1 / 0)   # an unscored take that is kept (a gated one is dropped)
    lid = _upload(client, tmp_path)
    sid = client.get(f"/lessons/{lid}").json()["segments"][0]["id"]
    sess = client.post("/sessions", json={"lesson_id": lid, "mode": "echo"}).json()
    wav = make_tone_wav(tmp_path / "a.wav", 1.0)
    with open(wav, "rb") as f:
        client.post(f"/segments/{sid}/attempts", files={"audio": ("a.wav", f, "audio/wav")}, data={"session_id": sess["id"], "mode": "echo"})
    ls = client.get(f"/lessons/{lid}/stats").json()
    assert ls["segments"][0]["attempts"] == 1 and ls["segments"][0]["last"] is None
    act = client.get("/stats/activity", params={"days": 7}).json()
    assert len(act["days"]) == 7 and act["days"][-1]["attempts"] == 1 and act["days"][-1]["minutes"] > 0
    assert client.get("/stats/sentences").json() == {"regressed": [], "by_last": []}
    assert client.get("/stats/syllables").json() == {"syllables": []}
    assert client.get("/stats/tones").json() == {"tones": [], "pairs": [], "weeks": []}


def test_lesson_stats_404(client):
    assert client.get("/lessons/9999/stats").status_code == 404


def _mk(client, ps_kwargs=None, att_secs=(), attach=True):
    """Insert a lesson segment, one session and attempts directly in the DB."""
    from datetime import datetime, timezone
    from sqlmodel import Session
    from shadow.store.models import Attempt, PracticeSession, Segment, Lesson
    with Session(client.app.state.engine) as db:
        lesson = Lesson(title="t", source_type="upload")
        db.add(lesson); db.commit(); db.refresh(lesson)
        seg = Segment(lesson_id=lesson.id, idx=0, start_s=0, end_s=1, text="x")
        db.add(seg); db.commit(); db.refresh(seg)
        sid = None
        if ps_kwargs is not None:
            ps = PracticeSession(lesson_id=lesson.id, mode="echo", **ps_kwargs)
            db.add(ps); db.commit(); db.refresh(ps)
            sid = ps.id
        for secs, created in att_secs:
            db.add(Attempt(segment_id=seg.id, session_id=sid if attach else None, mode="echo",
                           audio_path="x", duration_s=secs, created_at=created))
        db.commit()


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def test_activity_ended_session_counts_wall_time_once(client):
    from datetime import timedelta
    n = _now()
    _mk(client, {"started_at": n - timedelta(minutes=10), "ended_at": n}, [(30.0, n), (30.0, n)])
    day = client.get("/stats/activity", params={"days": 2}).json()["days"]
    total = sum(d["minutes"] for d in day)
    assert abs(total - 10.0) < 0.01 and sum(d["attempts"] for d in day) == 2


def test_activity_attempts_without_ended_session_count_durations(client):
    n = _now()
    _mk(client, None, [(60.0, n)], attach=False)
    _mk(client, {"started_at": n}, [(120.0, n)])
    total = sum(d["minutes"] for d in client.get("/stats/activity", params={"days": 2}).json()["days"])
    assert abs(total - 3.0) < 0.01


def test_activity_window_edge_session_before_window(client):
    from datetime import timedelta
    n = _now()
    # Session started well before the 2-day window; attempt falls inside it.
    _mk(client, {"started_at": n - timedelta(days=10), "ended_at": n - timedelta(days=9)}, [(90.0, n)])
    total = sum(d["minutes"] for d in client.get("/stats/activity", params={"days": 2}).json()["days"])
    assert abs(total - 1.5) < 0.01


def test_activity_ended_drill_counts_wall_time_once(client):
    from datetime import timedelta
    from sqlmodel import Session
    from shadow.store.models import Attempt, DrillSession, Lesson, Segment
    n = _now()
    with Session(client.app.state.engine) as db:
        les = Lesson(title="t", source_type="upload"); db.add(les); db.commit()
        seg = Segment(lesson_id=les.id, idx=0, start_s=0, end_s=1, text="x"); db.add(seg); db.commit()
        done = DrillSession(kind="tone", key="3", label="x", items_json=[], started_at=n - timedelta(minutes=10), ended_at=n)
        running = DrillSession(kind="tone", key="4", label="y", items_json=[], started_at=n)
        db.add(done); db.add(running); db.commit()
        for ds in (done, done, running):
            db.add(Attempt(segment_id=seg.id, drill_session_id=ds.id, mode="drill", audio_path="x", duration_s=30.0, created_at=n))
        db.commit()
    day = client.get("/stats/activity", params={"days": 2}).json()["days"]
    # The ended drill's 10 minutes of wall time, plus the 30 s take of the one still running.
    assert abs(sum(d["minutes"] for d in day) - 10.5) < 0.01 and sum(d["attempts"] for d in day) == 3


def test_activity_days_validation(client):
    assert client.get("/stats/activity", params={"days": 0}).status_code == 422
    assert client.get("/stats/activity", params={"days": 400}).status_code == 422


def _scores(client, rows):
    """rows: (tone, target_tone, prev_tone, tone_score, ch) on one attempt each, created now."""
    from sqlmodel import Session
    from shadow.store.models import Attempt, Lesson, Segment, SyllableScore
    with Session(client.app.state.engine) as db:
        les = Lesson(title="L", source_type="upload"); db.add(les); db.commit()
        seg = Segment(lesson_id=les.id, idx=0, start_s=0, end_s=1, text="好"); db.add(seg); db.commit()
        for tone, target, prev, score, ch in rows:
            a = Attempt(segment_id=seg.id, mode="echo", audio_path="x.wav", duration_s=1.0); db.add(a); db.commit()
            db.add(SyllableScore(attempt_id=a.id, segment_id=seg.id, idx=0, ch=ch, pinyin_toneless="hao", tone=tone,
                                 target_tone=target, prev_tone=prev, tone_score=score, status="ok"))
        db.commit()


def test_tone_stats_use_target_tones_and_weeks(client):
    _scores(client, [(3, 2, 3, 0.4, "你"), (3, 3, None, 0.8, "好"), (0, None, 3, None, "吗"), (-1, None, None, None, "A")])
    out = client.get("/stats/tones").json()
    assert {t["tone"]: t["n"] for t in out["tones"]} == {2: 1, 3: 1}
    assert out["pairs"] == [{"prev_tone": 3, "tone": 2, "mean": 0.4, "n": 1}]
    assert len(out["weeks"]) == 2 and all(w["week"].count("-W") == 1 for w in out["weeks"])


def test_syllable_stats_per_character_with_trend(client):
    _scores(client, [(3, 3, None, 0.2, "好")] * 10 + [(3, 3, None, 0.8, "好")] * 10 + [(4, 4, None, 0.9, "是")])
    out = client.get("/stats/syllables").json()["syllables"]
    hao = next(s for s in out if s["ch"] == "好")
    assert hao["n"] == 20 and hao["tone"] == 3 and abs(hao["trend"] - 0.6) < 1e-9
    assert next(s for s in out if s["ch"] == "是")["trend"] is None
    assert out[0]["ch"] == "好"                              # weakest first


def test_stats_sounds_rates_by_direction(client):
    from sqlmodel import Session
    from shadow.store.models import Attempt, Lesson, Segment, SyllableScore
    with Session(client.app.state.engine) as db:
        les = Lesson(title="t", source_type="upload"); db.add(les); db.commit(); db.refresh(les)
        seg = Segment(lesson_id=les.id, idx=0, start_s=0, end_s=1, text="x"); db.add(seg); db.commit(); db.refresh(seg)
        att = Attempt(segment_id=seg.id, mode="echo", audio_path="x", duration_s=1, created_at=_now()); db.add(att); db.commit()
        def row(i, py, st, heard=None):
            db.add(SyllableScore(attempt_id=att.id, segment_id=seg.id, idx=i, ch="x", pinyin_toneless=py, tone=1,
                                 status="ok", sound_status=st, heard_syllable=heard))
        for i in range(10):
            row(i, "Chi" if i == 0 else "chi", "slip" if i < 2 else "ok", "ci" if i < 2 else None)
        for i in range(5):
            row(20 + i, "ping", "ok")
        row(30, "chi", None)                                  # not checked: no chance
        db.commit()
    r = client.get("/stats/sounds").json()
    ch = next(s for s in r["sounds"] if s["key"] == "ch>c")
    assert (ch["slips"], ch["chances"], ch["rate"], ch["label"]) == (2, 10, 0.2, "ch said as c")
    assert all(s["key"] != "ng>n" for s in r["sounds"])
    assert r["weeks"] and all(w["key"] in {s["key"] for s in r["sounds"]} for w in r["weeks"])
    w = next(w for w in r["weeks"] if w["key"] == "ch>c")
    assert (w["slips"], w["chances"]) == (2, 10)
