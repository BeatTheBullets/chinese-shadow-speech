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
    act = client.get("/api/stats/activity", params={"days": 7}).json()
    assert len(act["days"]) == 7 and act["days"][-1]["attempts"] == 1 and act["days"][-1]["minutes"] > 0
    assert client.get("/api/stats/sentences").json() == {"sentences": []}
    assert client.get("/api/stats/characters").json() == {"characters": []}
    assert client.get("/api/stats/syllables").status_code == 404
    assert client.get("/api/stats/tones").json() == {"tones": [], "pairs": [], "weeks": []}


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
    day = client.get("/api/stats/activity", params={"days": 2}).json()["days"]
    total = sum(d["minutes"] for d in day)
    assert abs(total - 10.0) < 0.01 and sum(d["attempts"] for d in day) == 2


def test_activity_attempts_without_ended_session_count_durations(client):
    n = _now()
    _mk(client, None, [(60.0, n)], attach=False)
    _mk(client, {"started_at": n}, [(120.0, n)])
    total = sum(d["minutes"] for d in client.get("/api/stats/activity", params={"days": 2}).json()["days"])
    assert abs(total - 3.0) < 0.01


def test_activity_window_edge_session_before_window(client):
    from datetime import timedelta
    n = _now()
    # Session started well before the 2-day window; attempt falls inside it.
    _mk(client, {"started_at": n - timedelta(days=10), "ended_at": n - timedelta(days=9)}, [(90.0, n)])
    total = sum(d["minutes"] for d in client.get("/api/stats/activity", params={"days": 2}).json()["days"])
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
    day = client.get("/api/stats/activity", params={"days": 2}).json()["days"]
    # The ended drill's 10 minutes of wall time, plus the 30 s take of the one still running.
    assert abs(sum(d["minutes"] for d in day) - 10.5) < 0.01 and sum(d["attempts"] for d in day) == 3


def test_activity_days_validation(client):
    assert client.get("/api/stats/activity", params={"days": 0}).status_code == 422
    assert client.get("/api/stats/activity", params={"days": 400}).status_code == 422


def _scores(client, rows, *, days_ago=0, mode="echo"):
    """rows: (tone, target_tone, prev_tone, tone_score, ch[, status]) on one attempt each, created days_ago days back."""
    from datetime import timedelta
    from sqlmodel import Session
    from shadow.store.models import Attempt, Lesson, Segment, SyllableScore
    with Session(client.app.state.engine) as db:
        les = Lesson(title="L", source_type="upload"); db.add(les); db.commit()
        seg = Segment(lesson_id=les.id, idx=0, start_s=0, end_s=1, text="好"); db.add(seg); db.commit()
        for tone, target, prev, score, ch, *st in rows:
            a = Attempt(segment_id=seg.id, mode=mode, audio_path="x.wav", duration_s=1.0,
                        created_at=_now() - timedelta(days=days_ago)); db.add(a); db.commit()
            db.add(SyllableScore(attempt_id=a.id, segment_id=seg.id, idx=0, ch=ch, pinyin_toneless="hao", tone=tone,
                                 target_tone=target, prev_tone=prev, tone_score=score, status=st[0] if st else "ok"))
        db.commit()


def _take(client, seg_id, *, days_ago, overall, mode="echo"):
    from datetime import timedelta
    from sqlmodel import Session
    from shadow.store.models import Attempt
    with Session(client.app.state.engine) as db:
        db.add(Attempt(segment_id=seg_id, mode=mode, audio_path="x.wav", duration_s=1.0,
                       score_json=None if overall is None else {"overall": overall},
                       created_at=_now() - timedelta(days=days_ago)))
        db.commit()


def test_tone_stats_use_target_tones_and_weeks(client):
    _scores(client, [(3, 2, 3, 0.4, "你"), (3, 3, None, 0.8, "好"), (0, None, 3, None, "吗"), (-1, None, None, None, "A")])
    out = client.get("/api/stats/tones").json()
    assert {t["tone"]: t["n"] for t in out["tones"]} == {2: 1, 3: 1}
    assert out["pairs"] == [{"prev_tone": 3, "tone": 2, "mean": 0.4, "n": 1}]
    assert len(out["weeks"]) == 2 and all(w["week"].count("-W") == 1 for w in out["weeks"])


def test_characters_endpoint(client):
    _scores(client, [(3, 3, None, 0.2, "好")] * 10 + [(3, 3, None, 0.8, "好", "wrong")] * 5 + [(4, 4, None, 0.9, "是")] * 3)
    out = client.get("/api/stats/characters").json()["characters"]
    hao = next(c for c in out if c["ch"] == "好")
    assert hao["takes"] == 15 and abs(hao["score"] - 10 / 15) < 1e-9 and hao["pinyin"] == "hǎo"
    assert abs(hao["tone_right"] - 10 / 15) < 1e-9 and hao["sound_right"] is None
    assert abs(hao["trend"] - (-0.5)) < 1e-9          # last 10 right 0.5 against the first 5 at 1.0
    assert next(c for c in out if c["ch"] == "是")["trend"] is None
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
        for i in range(5):
            row(40 + i, "ding", "ok")                         # din has no characters: ng>n is never checked on ding
        db.commit()
    r = client.get("/api/stats/sounds").json()
    ch = next(s for s in r["sounds"] if s["key"] == "ch>c")
    assert (ch["slips"], ch["chances"], ch["rate"], ch["label"]) == (2, 10, 0.2, "ch said as c")
    assert all(s["key"] != "ng>n" for s in r["sounds"])   # 5 ping chances; the 5 ding rows add none
    assert r["weeks"] and all(w["key"] in {s["key"] for s in r["sounds"]} for w in r["weeks"])
    w = next(w for w in r["weeks"] if w["key"] == "ch>c")
    assert (w["slips"], w["chances"]) == (2, 10)


def test_tones_window_and_missing_rule(client):
    _scores(client, [(3, 3, 2, 0.8, "好")])
    _scores(client, [(3, 3, None, None, "好", "missing")])
    _scores(client, [(3, 3, 2, 0.1, "好"), (1, 1, None, 0.5, "妈", "unvoiced")], days_ago=40)
    out = client.get("/api/stats/tones").json()
    assert out["tones"] == [{"tone": 3, "mean": 0.4, "n": 2}]
    assert out["pairs"] == [{"prev_tone": 2, "tone": 3, "mean": 0.8, "n": 1}]
    assert sum(w["n"] for w in out["weeks"] if w["tone"] == 3) == 3     # the old row is in the weeks
    assert all(w["tone"] != 1 for w in out["weeks"])                    # unvoiced left out


def _slips(client, days_ago, mode="echo"):
    from datetime import timedelta
    from sqlmodel import Session
    from shadow.store.models import Attempt, Lesson, Segment, SyllableScore
    with Session(client.app.state.engine) as db:
        les = Lesson(title="t", source_type="upload"); db.add(les); db.commit(); db.refresh(les)
        seg = Segment(lesson_id=les.id, idx=0, start_s=0, end_s=1, text="x"); db.add(seg); db.commit(); db.refresh(seg)
        att = Attempt(segment_id=seg.id, mode=mode, audio_path="x", duration_s=1,
                      created_at=_now() - timedelta(days=days_ago)); db.add(att); db.commit()
        for i in range(10):
            db.add(SyllableScore(attempt_id=att.id, segment_id=seg.id, idx=i, ch="x", pinyin_toneless="chi", tone=1,
                                 status="ok", sound_status="slip" if i < 2 else "ok", heard_syllable="ci" if i < 2 else None))
        db.commit()


def test_sounds_window_and_hard_flag(client):
    _slips(client, 1)
    out = client.get("/api/stats/sounds").json()
    assert next(s for s in out["sounds"] if s["key"] == "ch>c")["hard"] is True
    assert all(isinstance(s["hard"], bool) for s in out["sounds"])
    assert out["weeks"]
    _slips(client, 40)                                   # outside the 30 days: not counted in the rows
    ch = next(s for s in client.get("/api/stats/sounds").json()["sounds"] if s["key"] == "ch>c")
    assert (ch["slips"], ch["chances"]) == (2, 10)


def test_sentences_window_last_and_best_ever(client):
    from sqlmodel import Session
    from shadow.store.models import Lesson, Segment
    with Session(client.app.state.engine) as db:
        les = Lesson(title="Les", source_type="upload"); db.add(les); db.commit()
        a = Segment(lesson_id=les.id, idx=3, start_s=0, end_s=1, text="甲"); b = Segment(lesson_id=les.id, idx=4, start_s=1, end_s=2, text="乙")
        db.add(a); db.add(b); db.commit()
        ids = (les.id, a.id, b.id)
    lid, aid, bid = ids
    _take(client, aid, days_ago=60, overall=0.9)
    _take(client, aid, days_ago=2, overall=0.6)
    _take(client, bid, days_ago=60, overall=0.8)
    _take(client, bid, days_ago=1, overall=None)
    rows = client.get("/api/stats/sentences").json()["sentences"]
    assert rows == [{"segment_id": aid, "lesson_id": lid, "lesson_title": "Les", "idx": 3, "text": "甲",
                     "last": 0.6, "best": 0.9, "attempts": 1, "regressed": True}]


def test_mode_filter_flow_only(client):
    _scores(client, [(3, 3, 2, 0.8, "好")])
    _slips(client, 1)
    for path, key in (("characters", "characters"), ("tones", "tones"), ("sounds", "sounds")):
        assert client.get(f"/api/stats/{path}", params={"mode": "flow"}).json()[key] == []
        assert client.get(f"/api/stats/{path}", params={"mode": "echo"}).status_code == 422
    assert client.get("/api/stats/tones", params={"mode": "flow"}).json() == {"tones": [], "pairs": [], "weeks": []}
    _scores(client, [(3, 3, 2, 0.8, "好")], mode="flow")
    assert client.get("/api/stats/tones", params={"mode": "flow"}).json()["tones"] == [{"tone": 3, "mean": 0.8, "n": 1}]


def test_overview_scores_and_weekly_change(client):
    _scores(client, [(3, 3, None, 1.0, "好")] * 30, days_ago=2)
    _scores(client, [(3, 3, None, 0.5, "好")] * 30, days_ago=10)
    t = client.get("/api/stats/overview").json()["scores"]["tones"]
    assert t["n"] == 60 and abs(t["value"] - 0.75) < 1e-9 and abs(t["last7"] - 1.0) < 1e-9 and abs(t["prev7"] - 0.5) < 1e-9
    _scores(client, [(3, 3, None, 0.2, "好")] * 30, days_ago=2, mode="flow")
    flow = client.get("/api/stats/overview").json()["flow"]["tones"]
    assert abs(flow["value"] - 0.2) < 1e-9 and flow["prev7"] is None


def test_overview_lists_and_activity(client):
    from datetime import timedelta
    from sqlmodel import Session
    from shadow.store.models import Attempt, DrillSession, Lesson, Segment
    with Session(client.app.state.engine) as db:
        les = Lesson(title="Les", source_type="upload"); db.add(les); db.commit()
        segs = [Segment(lesson_id=les.id, idx=i, start_s=0, end_s=1, text=f"句{i}") for i in range(4)]
        db.add_all(segs); db.commit()
        ids = [s.id for s in segs]
        n = _now()
        for k in range(3):
            ds = DrillSession(kind="tone", key=str(k), label="x", items_json=[{"segment_id": ids[0], "targets": []}],
                              started_at=n - timedelta(minutes=5), ended_at=n - timedelta(minutes=k))
            db.add(ds); db.commit(); db.refresh(ds)
            db.add(Attempt(segment_id=ids[0], drill_session_id=ds.id, mode="drill", audio_path="x", duration_s=1.0,
                           score_json={"overall": 0.5}, created_at=n))
        db.commit()
    for i, sid in enumerate(ids):
        _take(client, sid, days_ago=1, overall=0.3 + 0.1 * i)
    _take(client, ids[0], days_ago=8, overall=0.9)
    _scores(client, [(3, 3, None, 0.9, "好")] * 7, days_ago=1)
    out = client.get("/api/stats/overview").json()
    assert len(out["sentences"]) == 3 and all(s["text"] for s in out["sentences"])
    assert len(out["drills"]) == 2
    # 3 drill takes + 4 sentence takes + 7 syllable-attempts within 7 days, on today and yesterday; the take 8 days ago does not count.
    assert out["activity"]["takes"] == 14 and out["activity"]["days"] == 2
    assert out["weakest"]["characters"] == []


def test_overview_empty(client):
    r = client.get("/api/stats/overview")
    assert r.status_code == 200
    out = r.json()
    for key in ("scores", "flow"):
        for s in out[key].values():
            assert s["value"] is None and s["n"] == 0
    assert out["weakest"] == {"characters": [], "tones": [], "sounds": []}
    assert out["sentences"] == [] and out["drills"] == []
    assert out["activity"] == {"minutes": 0.0, "takes": 0, "days": 0}
