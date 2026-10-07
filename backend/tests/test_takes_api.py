from datetime import datetime, timedelta, timezone
from sqlmodel import Session
from shadow.store.models import Attempt, PracticeSession
from tests.test_lessons_api import _statements, _upload

T0 = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)


def _segs(client, lid) -> list[int]:
    return [s["id"] for s in client.get(f"/lessons/{lid}").json()["segments"]]


def _session(client, lid) -> int:
    with Session(client.app.state.engine) as db:
        s = PracticeSession(lesson_id=lid, mode="echo")
        db.add(s); db.commit(); db.refresh(s)
        return s.id


def _att(client, sid, at_s: float, mode="flow", session_id=None, audio=True) -> int:
    """An attempt on sentence `sid` at T0 + at_s seconds, with its audio file on disk unless `audio` is False."""
    files = client.app.state.files
    with Session(client.app.state.engine) as db:
        a = Attempt(segment_id=sid, session_id=session_id, mode=mode, audio_path="", duration_s=1.5,
                    created_at=T0 + timedelta(seconds=at_s))
        db.add(a); db.commit(); db.refresh(a)
        wav = files.attempt_wav(a.id)
        a.audio_path = str(wav)
        if audio:
            wav.write_bytes(b"RIFF")
        db.add(a); db.commit()
        return a.id


# --- latest take per sentence -----------------------------------------------------------------------------------

def test_takes_unknown_lesson_404(client):
    assert client.get("/lessons/999/takes").status_code == 404


def test_takes_empty_without_attempts(client, tmp_path):
    lid = _upload(client, tmp_path)
    assert client.get(f"/lessons/{lid}/takes").json() == {"takes": []}


def test_takes_are_the_latest_attempt_of_each_sentence_in_any_mode(client, tmp_path):
    lid = _upload(client, tmp_path)
    s0, s1, s2 = _segs(client, lid)
    _att(client, s0, 0, mode="echo")
    latest0 = _att(client, s0, 30, mode="flow")
    _att(client, s1, 50, mode="flow")
    latest1 = _att(client, s1, 60, mode="chorus")
    out = client.get(f"/lessons/{lid}/takes").json()["takes"]
    assert [(t["segment_id"], t["attempt_id"], t["mode"]) for t in out] == [(s0, latest0, "flow"), (s1, latest1, "chorus")]
    assert out[0]["duration_s"] == 1.5 and out[0]["created_at"].startswith("2026-10-07T09:00:30")
    assert out[0]["created_at"].endswith(("Z", "+00:00"))          # UTC, so the browser shows local time
    assert s2 not in [t["segment_id"] for t in out]


def test_takes_tie_on_time_goes_to_the_higher_id(client, tmp_path):
    lid = _upload(client, tmp_path)
    s0 = _segs(client, lid)[0]
    _att(client, s0, 10)
    second = _att(client, s0, 10)
    assert [t["attempt_id"] for t in client.get(f"/lessons/{lid}/takes").json()["takes"]] == [second]


def test_takes_skip_attempts_without_audio(client, tmp_path):
    lid = _upload(client, tmp_path)
    s0, s1, _ = _segs(client, lid)
    older = _att(client, s0, 0)
    _att(client, s0, 10, audio=False)                             # file gone: the older take is the latest playable
    _att(client, s1, 0, audio=False)
    with Session(client.app.state.engine) as db:                    # an upload still being decoded has no audio path yet
        db.add(Attempt(segment_id=s0, mode="echo", audio_path="", duration_s=0.0, created_at=T0 + timedelta(seconds=20)))
        db.commit()
    assert [(t["segment_id"], t["attempt_id"]) for t in client.get(f"/lessons/{lid}/takes").json()["takes"]] == [(s0, older)]


def test_takes_only_cover_this_lesson(client, tmp_path):
    a, b = _upload(client, tmp_path, "A"), _upload(client, tmp_path, "B")
    _att(client, _segs(client, b)[0], 0)
    mine = _att(client, _segs(client, a)[1], 0)
    assert [t["attempt_id"] for t in client.get(f"/lessons/{a}/takes").json()["takes"]] == [mine]


def test_takes_cost_one_attempt_query_however_many_sentences(client, tmp_path):
    lid = _upload(client, tmp_path)
    s0, s1, s2 = _segs(client, lid)
    _att(client, s0, 0)
    one = _statements(client.app.state.engine, lambda: client.get(f"/lessons/{lid}/takes").json())
    for k, s in enumerate((s0, s1, s2, s1, s2)):
        _att(client, s, 10 + k)
    assert _statements(client.app.state.engine, lambda: client.get(f"/lessons/{lid}/takes").json()) == one == 2  # lesson + attempts


# --- Flow runs ---------------------------------------------------------------------------------------------------

def _runs(client, lid):
    r = client.get(f"/lessons/{lid}/flow-runs")
    assert r.status_code == 200
    return r.json()["runs"]


def test_flow_runs_unknown_lesson_404(client):
    assert client.get("/lessons/999/flow-runs").status_code == 404


def test_flow_runs_only_count_flow_attempts(client, tmp_path):
    lid = _upload(client, tmp_path)
    s0, s1, _ = _segs(client, lid)
    sess = _session(client, lid)
    _att(client, s0, 0, mode="echo", session_id=sess)
    _att(client, s1, 5, mode="chorus", session_id=sess)
    assert _runs(client, lid) == []
    flow = _att(client, s1, 10, session_id=sess)
    runs = _runs(client, lid)
    assert [[(i["segment_id"], i["idx"], i["attempt_id"]) for i in r["items"]] for r in runs] == [[(s1, 1, flow)]]
    assert runs[0]["session_id"] == sess


def test_flow_run_items_in_sentence_order_with_the_latest_take_of_a_repeated_sentence(client, tmp_path):
    lid = _upload(client, tmp_path)
    s0, s1, s2 = _segs(client, lid)
    sess = _session(client, lid)
    _att(client, s2, 0, session_id=sess)                          # uploads may land in any order
    a0 = _att(client, s0, 2, session_id=sess)
    _att(client, s1, 4, session_id=sess)
    b1 = _att(client, s1, 6, session_id=sess)                     # the same sentence twice within one run: the later one
    run = _runs(client, lid)[0]
    assert [(i["segment_id"], i["idx"]) for i in run["items"]] == [(s0, 0), (s1, 1), (s2, 2)]
    assert [i["attempt_id"] for i in run["items"]][:2] == [a0, b1]
    assert run["started_at"].startswith("2026-10-07T09:00:00") and run["ended_at"].startswith("2026-10-07T09:00:06")


def test_a_session_splits_into_runs_at_gaps_over_a_minute(client, tmp_path):
    lid = _upload(client, tmp_path)
    s0, s1, s2 = _segs(client, lid)
    sess = _session(client, lid)
    _att(client, s0, 0, session_id=sess)
    _att(client, s1, 60, session_id=sess)                         # exactly 60 s apart: still the same run
    _att(client, s2, 121, session_id=sess)                        # 61 s later: a new run
    _att(client, s0, 125, session_id=sess)
    runs = _runs(client, lid)
    assert [[i["segment_id"] for i in r["items"]] for r in runs] == [[s0, s2], [s0, s1]]   # newest first
    assert all(r["session_id"] == sess for r in runs)


def test_runs_never_span_sessions_and_attempts_without_a_session_group_together(client, tmp_path):
    lid = _upload(client, tmp_path)
    s0, s1, s2 = _segs(client, lid)
    one, two = _session(client, lid), _session(client, lid)
    _att(client, s0, 0, session_id=one)
    _att(client, s1, 5, session_id=two)                           # 5 s later but another visit: another run
    _att(client, s1, 20, session_id=None)
    _att(client, s2, 25, session_id=None)
    runs = _runs(client, lid)
    assert [(r["session_id"], [i["segment_id"] for i in r["items"]]) for r in runs] == [(None, [s1, s2]), (two, [s1]), (one, [s0])]


def test_at_most_ten_runs_newest_first(client, tmp_path):
    lid = _upload(client, tmp_path)
    s0 = _segs(client, lid)[0]
    sess = _session(client, lid)
    ids = [_att(client, s0, k * 120, session_id=sess) for k in range(12)]
    runs = _runs(client, lid)
    assert [r["items"][0]["attempt_id"] for r in runs] == ids[::-1][:10]


def test_runs_without_a_playable_take_do_not_count_toward_the_ten(client, tmp_path):
    lid = _upload(client, tmp_path)
    s0 = _segs(client, lid)[0]
    sess = _session(client, lid)
    ids = [_att(client, s0, k * 120, session_id=sess) for k in range(10)]
    _att(client, s0, 10 * 120, session_id=sess, audio=False)        # the newest run lost its audio
    assert [r["items"][0]["attempt_id"] for r in _runs(client, lid)] == ids[::-1]


def test_flow_runs_skip_attempts_without_audio(client, tmp_path):
    lid = _upload(client, tmp_path)
    s0, s1, _ = _segs(client, lid)
    sess = _session(client, lid)
    kept = _att(client, s0, 0, session_id=sess)
    _att(client, s1, 2, session_id=sess, audio=False)
    assert [[i["attempt_id"] for i in r["items"]] for r in _runs(client, lid)] == [[kept]]


def test_flow_runs_follow_a_merge(client, tmp_path):
    lid = _upload(client, tmp_path)
    s0, s1, s2 = _segs(client, lid)
    sess = _session(client, lid)
    _att(client, s0, 0, session_id=sess)
    later = _att(client, s1, 2, session_id=sess)
    third = _att(client, s2, 4, session_id=sess)
    assert client.post(f"/segments/{s0}/merge-next").status_code == 200       # s1's attempts move to s0, s1 is gone
    run = _runs(client, lid)[0]
    assert [(i["segment_id"], i["idx"], i["attempt_id"]) for i in run["items"]] == [(s0, 0, later), (s2, 1, third)]
