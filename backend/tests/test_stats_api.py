from tests.helpers import make_tone_wav
from tests.test_lessons_api import _upload


def test_stats_shapes(client, tmp_path):
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
    assert client.get("/stats/tones").json() == {"tones": [], "pairs": []}


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


def test_activity_days_validation(client):
    assert client.get("/stats/activity", params={"days": 0}).status_code == 422
    assert client.get("/stats/activity", params={"days": 400}).status_code == 422
