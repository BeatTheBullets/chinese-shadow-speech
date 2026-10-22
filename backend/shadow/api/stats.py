from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlmodel import Session, select
from shadow.scoring.sounds.contrasts import direction, direction_label, directions_of
from shadow.store.db import get_session
from shadow.store.models import Attempt, DrillSession, Lesson, PracticeSession, Segment, SyllableScore

router = APIRouter()


def _overall(a: Attempt) -> float | None:
    return a.score_json.get("overall") if a.score_json else None


def _utc_day(dt: datetime) -> str:
    # SQLite returns naive datetimes; they were written as UTC.
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return str(dt.date())


@router.get("/lessons/{lesson_id}/stats")
def lesson_stats(lesson_id: int, db: Session = Depends(get_session)):
    if db.get(Lesson, lesson_id) is None:
        raise HTTPException(404, "lesson not found")
    segs = db.exec(select(Segment).where(Segment.lesson_id == lesson_id).order_by(Segment.idx)).all()
    out_segments = []
    for s in segs:
        atts = db.exec(select(Attempt).where(Attempt.segment_id == s.id).order_by(Attempt.created_at)).all()
        scores = [x for x in (_overall(a) for a in atts) if x is not None]
        out_segments.append({"segment_id": s.id, "idx": s.idx, "last": scores[-1] if scores else None,
                             "best": max(scores) if scores else None, "attempts": len(atts), "trend": scores})
    sessions = []
    for ps in db.exec(select(PracticeSession).where(PracticeSession.lesson_id == lesson_id).order_by(PracticeSession.started_at)).all():
        scores = [x for x in (_overall(a) for a in db.exec(select(Attempt).where(Attempt.session_id == ps.id)).all()) if x is not None]
        sessions.append({"session_id": ps.id, "started_at": ps.started_at, "mean": sum(scores) / len(scores) if scores else None})
    return {"segments": out_segments, "sessions": sessions}


@router.get("/stats/activity")
def activity(days: int = Query(30, ge=1, le=366), db: Session = Depends(get_session)):
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    per_day: dict[str, dict] = {str(start + timedelta(d)): {"date": str(start + timedelta(d)), "minutes": 0.0, "attempts": 0} for d in range(days)}
    # Aware UTC bound: the column type rejects naive bind values.
    since = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    # A session's wall time is credited to its start day; only sessions credited inside the window suppress their attempts' durations.
    ended = db.exec(select(PracticeSession).where(PracticeSession.ended_at.is_not(None), PracticeSession.started_at >= since)).all()
    ended_ids = {ps.id for ps in ended}
    # Drills the same way: their takes are attempts with drill_session_id instead of session_id.
    drills = db.exec(select(DrillSession).where(DrillSession.ended_at.is_not(None), DrillSession.started_at >= since)).all()
    drill_ids = {ds.id for ds in drills}
    for a in db.exec(select(Attempt).where(Attempt.created_at >= since)).all():
        key = _utc_day(a.created_at)
        if key in per_day:
            per_day[key]["attempts"] += 1
            # Ended sessions contribute wall time below instead of attempt durations.
            if a.session_id not in ended_ids and a.drill_session_id not in drill_ids:
                per_day[key]["minutes"] += a.duration_s / 60
    for ps in [*ended, *drills]:
        key = _utc_day(ps.started_at)
        if key in per_day:
            per_day[key]["minutes"] += (ps.ended_at - ps.started_at).total_seconds() / 60
    return {"days": [per_day[k] for k in sorted(per_day)]}


@router.get("/stats/sentences")
def sentences(db: Session = Depends(get_session)):
    by_seg: dict[int, list[float]] = defaultdict(list)
    for a in db.exec(select(Attempt).order_by(Attempt.created_at)).all():
        o = _overall(a)
        if o is not None:
            by_seg[a.segment_id].append(o)
    rows = [{"segment_id": sid, "last": v[-1], "best": max(v), "attempts": len(v)} for sid, v in by_seg.items()]
    return {"regressed": sorted([r for r in rows if r["best"] - r["last"] >= 0.15], key=lambda r: r["best"] - r["last"], reverse=True),
            "by_last": sorted(rows, key=lambda r: r["last"])}


_TONE = func.coalesce(SyllableScore.target_tone, SyllableScore.tone)   # the tone the speaker produced, when known
_SCORED = SyllableScore.tone_score.is_not(None)


@router.get("/stats/syllables")
def syllables(db: Session = Depends(get_session)):
    """Per character, oldest first: mean, count, most frequent target tone, and the last 10 against the rest."""
    q = (select(SyllableScore.ch, SyllableScore.pinyin_toneless, _TONE, SyllableScore.tone_score)
         .where(_SCORED, _TONE >= 0).order_by(SyllableScore.attempt_id, SyllableScore.idx))
    by_ch: dict[str, dict] = {}
    for ch, pinyin, tone, score in db.exec(q).all():
        d = by_ch.setdefault(ch, {"pinyin": pinyin, "tones": Counter(), "scores": []})
        d["tones"][tone] += 1; d["scores"].append(score)
    out = []
    for ch, d in by_ch.items():
        s = d["scores"]
        trend = sum(s[-10:]) / 10 - sum(s[:-10]) / len(s[:-10]) if len(s) >= 15 else None
        out.append({"ch": ch, "pinyin": d["pinyin"], "tone": d["tones"].most_common(1)[0][0], "mean": sum(s) / len(s),
                    "n": len(s), "trend": trend})
    return {"syllables": sorted(out, key=lambda r: r["mean"])[:50]}


@router.get("/stats/tones")
def tones(db: Session = Depends(get_session)):
    q1 = select(_TONE, func.avg(SyllableScore.tone_score), func.count()).where(_SCORED, _TONE >= 0).group_by(_TONE)
    q2 = (select(SyllableScore.prev_tone, _TONE, func.avg(SyllableScore.tone_score), func.count())
          .where(_SCORED, _TONE >= 0, SyllableScore.prev_tone >= 0).group_by(SyllableScore.prev_tone, _TONE))
    since = datetime.combine(datetime.now(timezone.utc).date() - timedelta(weeks=12), datetime.min.time(), tzinfo=timezone.utc)
    q3 = (select(Attempt.created_at, _TONE, SyllableScore.tone_score).join(Attempt, Attempt.id == SyllableScore.attempt_id)
          .where(_SCORED, _TONE >= 0, Attempt.created_at >= since))
    weeks: dict[tuple[str, int], list[float]] = defaultdict(list)
    for created, tone, score in db.exec(q3).all():
        y, w, _ = created.isocalendar()
        weeks[(f"{y}-W{w:02d}", tone)].append(score)
    return {"tones": [{"tone": t, "mean": m, "n": n} for t, m, n in db.exec(q1).all()],
            "pairs": [{"prev_tone": p, "tone": t, "mean": m, "n": n} for p, t, m, n in db.exec(q2).all()],
            "weeks": [{"week": wk, "tone": t, "mean": sum(v) / len(v), "n": len(v)} for (wk, t), v in sorted(weeks.items())]}


_MIN_CHANCES = 8   # fewer checked syllables than this say too little about a direction


@router.get("/stats/sounds")
def sounds(db: Session = Depends(get_session)):
    """Slip rate per sound direction. Every checked syllable is a chance for each direction its pinyin offers;
    a slip counts for the direction actually heard."""
    since = datetime.combine(datetime.now(timezone.utc).date() - timedelta(weeks=12), datetime.min.time(), tzinfo=timezone.utc)
    q = (select(SyllableScore.pinyin_toneless, SyllableScore.sound_status, SyllableScore.heard_syllable, Attempt.created_at)
         .join(Attempt, Attempt.id == SyllableScore.attempt_id).where(SyllableScore.sound_status.is_not(None)))
    tot: dict[str, list[int]] = defaultdict(lambda: [0, 0])                       # key -> [slips, chances]
    wk: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for py, status, heard, created in db.exec(q).all():
        py = py.lower()
        slip = direction(py, heard.lower()) if status == "slip" and heard else None
        y, w, _ = created.isocalendar()
        recent = (created if created.tzinfo else created.replace(tzinfo=timezone.utc)) >= since
        for key in directions_of(py):
            hit = key == slip
            tot[key][0] += hit; tot[key][1] += 1
            if recent:
                wk[(f"{y}-W{w:02d}", key)][0] += hit; wk[(f"{y}-W{w:02d}", key)][1] += 1
    kept = {k: v for k, v in tot.items() if v[1] >= _MIN_CHANCES}
    rows = [{"key": k, "label": direction_label(k), "slips": s, "chances": c, "rate": s / c} for k, (s, c) in kept.items()]
    rows.sort(key=lambda r: (-r["rate"], -r["chances"], r["key"]))
    return {"sounds": rows,
            "weeks": [{"week": w, "key": k, "rate": s / c, "slips": s, "chances": c}
                      for (w, k), (s, c) in sorted(wk.items()) if k in kept]}
