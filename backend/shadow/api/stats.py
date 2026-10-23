from __future__ import annotations
from collections import defaultdict
from typing import Literal
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select
from shadow.scoring.sounds.contrasts import checkable_directions_of, direction
from shadow.stats.scores import SylRow, character_stats, rank_sentences, sound_directions, tone_groups, tone_value
from shadow.store.db import get_session
from shadow.store.models import Attempt, DrillSession, Lesson, PracticeSession, Segment, SyllableScore

router = APIRouter(prefix="/api/stats")
lesson_router = APIRouter()


def _overall(a: Attempt) -> float | None:
    return a.score_json.get("overall") if a.score_json else None


def _utc_day(dt: datetime) -> str:
    # SQLite returns naive datetimes; they were written as UTC.
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return str(dt.date())


@lesson_router.get("/lessons/{lesson_id}/stats")
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


def _activity_days(db: Session, days: int) -> list[dict]:
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
    return [per_day[k] for k in sorted(per_day)]




@router.get("/activity")
def activity(days: int = Query(30, ge=1, le=366), db: Session = Depends(get_session)):
    return {"days": _activity_days(db, days)}


WINDOW_DAYS = 30
WEEKS = 12
Mode = Literal["flow"] | None


def _aware(dt: datetime) -> datetime:
    # SQLite returns naive datetimes; they were written as UTC.
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _since(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def _rows(db: Session, since: datetime, mode: str | None) -> list[SylRow]:
    q = (select(SyllableScore, Attempt.created_at).join(Attempt, Attempt.id == SyllableScore.attempt_id)
         .where(Attempt.created_at >= since))
    if mode is not None:
        q = q.where(Attempt.mode == mode)
    return [SylRow(ch=s.ch, pinyin=s.pinyin_toneless.lower(), tone=s.target_tone if s.target_tone is not None else s.tone,
                   prev_tone=s.prev_tone, tone_score=s.tone_score, status=s.status, sound_status=s.sound_status,
                   heard=s.heard_syllable.lower() if s.heard_syllable else None, created_at=_aware(created),
                   attempt_id=s.attempt_id, idx=s.idx)
            for s, created in db.exec(q).all()]


def _week(r: SylRow) -> str:
    y, w, _ = r.created_at.isocalendar()
    return f"{y}-W{w:02d}"


@router.get("/characters")
def characters(mode: Mode = None, db: Session = Depends(get_session)):
    return {"characters": character_stats(_rows(db, _since(WINDOW_DAYS), mode))}


@router.get("/tones")
def tones(mode: Mode = None, db: Session = Depends(get_session)):
    rows = _rows(db, _since(WEEKS * 7), mode)
    cut = _since(WINDOW_DAYS)
    groups, pairs = tone_groups([r for r in rows if r.created_at >= cut])
    weeks: dict[tuple[str, int], list[float]] = defaultdict(list)
    for r in rows:
        if 0 <= r.tone <= 4 and (v := tone_value(r)) is not None:
            weeks[(_week(r), r.tone)].append(v)
    return {"tones": groups, "pairs": pairs,
            "weeks": [{"week": wk, "tone": t, "mean": sum(v) / len(v), "n": len(v)} for (wk, t), v in sorted(weeks.items())]}


@router.get("/sounds")
def sounds(mode: Mode = None, db: Session = Depends(get_session)):
    rows = _rows(db, _since(WEEKS * 7), mode)
    cut = _since(WINDOW_DAYS)
    out = sound_directions([r for r in rows if r.created_at >= cut])
    kept = {d["key"] for d in out}
    wk: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])          # (week, key) -> [slips, chances]
    for r in rows:
        if r.sound_status is None:
            continue
        slip = direction(r.pinyin, r.heard) if r.sound_status == "slip" and r.heard else None
        for key in checkable_directions_of(r.pinyin):
            if key in kept:
                wk[(_week(r), key)][0] += key == slip
                wk[(_week(r), key)][1] += 1
    return {"sounds": out,
            "weeks": [{"week": w, "key": k, "rate": s / c, "slips": s, "chances": c} for (w, k), (s, c) in sorted(wk.items())]}


def _sentences(db: Session, since: datetime) -> list[dict]:
    """Every sentence with a scored take since `since`, ranked: last and attempts from the window, best from all time."""
    best: dict[int, float] = {}
    window: dict[int, list[float]] = defaultdict(list)
    since = _aware(since)
    for a in db.exec(select(Attempt).where(Attempt.score_json.is_not(None)).order_by(Attempt.created_at, Attempt.id)).all():
        o = _overall(a)
        if o is None:
            continue
        best[a.segment_id] = max(best.get(a.segment_id, o), o)
        if _aware(a.created_at) >= since:
            window[a.segment_id].append(o)
    if not window:
        return []
    info = {s.id: (s, l.title) for s, l in db.exec(select(Segment, Lesson).join(Lesson, Lesson.id == Segment.lesson_id)
                                                   .where(Segment.id.in_(list(window)))).all()}
    return rank_sentences([{"segment_id": sid, "lesson_id": info[sid][0].lesson_id, "lesson_title": info[sid][1],
                            "idx": info[sid][0].idx, "text": info[sid][0].text, "last": v[-1], "best": best[sid],
                            "attempts": len(v)} for sid, v in window.items() if sid in info])


@router.get("/sentences")
def sentences(db: Session = Depends(get_session)):
    return {"sentences": _sentences(db, _since(WINDOW_DAYS))}
