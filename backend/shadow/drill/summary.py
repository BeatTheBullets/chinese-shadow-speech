"""Drill summaries (Phase 3b spec §3): first and best take per sentence, totals, and the focus's history."""
from __future__ import annotations
from sqlmodel import Session, select
from shadow.store.models import Attempt, DrillSession, Lesson, Segment, SyllableScore


def target_mean(rows: dict[int, tuple[str, float | None]], targets: list[int]) -> tuple[float | None, int]:
    vals, green = [], 0
    for i in targets:
        status, score = rows.get(i, ("unvoiced", None))
        if status == "unvoiced":
            continue
        vals.append(0.0 if status == "missing" else (score or 0.0))
        green += status == "ok"
    return (sum(vals) / len(vals) if vals else None), green


def _takes(db: Session, ds: DrillSession, segment_id: int, targets: list[int]) -> list[dict]:
    """Scored drill takes of the sentence in this session, oldest first, with their target mean and green count."""
    atts = db.exec(select(Attempt).where(Attempt.drill_session_id == ds.id, Attempt.segment_id == segment_id)
                   .order_by(Attempt.created_at, Attempt.id)).all()
    out = []
    for a in atts:
        if not a.score_json or a.score_json.get("overall") is None:
            continue
        rows = {r.idx: (r.status, r.tone_score) for r in db.exec(select(SyllableScore).where(SyllableScore.attempt_id == a.id)).all()}
        mean, green = target_mean(rows, targets)
        out.append({"attempt_id": a.id, "mean": mean, "green": green})
    return out


def _mean(xs: list[float | None]) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _totals(db: Session, ds: DrillSession) -> dict:
    items = []
    for it in ds.items_json or []:
        seg = db.get(Segment, it["segment_id"])
        if seg is None:
            continue
        takes = _takes(db, ds, seg.id, it["targets"])
        first = takes[0] if takes else None
        best = max(takes, key=lambda t: (t["mean"] if t["mean"] is not None else -1)) if takes else None
        items.append({"segment_id": seg.id, "lesson_id": seg.lesson_id, "lesson_title": db.get(Lesson, seg.lesson_id).title,
                      "idx": seg.idx, "text": seg.text, "targets": it["targets"], "tries": len(takes), "first": first, "best": best,
                      "went_green": any(t["green"] == len(it["targets"]) for t in takes)})
    tried = [i for i in items if i["tries"]]
    return {"items": items,
            "first_mean": _mean([i["first"]["mean"] for i in tried]), "best_mean": _mean([i["best"]["mean"] for i in tried]),
            "green_first": sum(i["first"]["green"] for i in tried), "green_best": sum(i["best"]["green"] for i in tried),
            "n_targets": sum(len(i["targets"]) for i in tried)}


def session_summary(db: Session, ds: DrillSession) -> dict:
    tot = _totals(db, ds)
    past = db.exec(select(DrillSession).where(DrillSession.kind == ds.kind, DrillSession.key == ds.key,
                                              DrillSession.ended_at.is_not(None))
                   .order_by(DrillSession.started_at.desc(), DrillSession.id.desc()).limit(10)).all()
    history = []
    for p in reversed(past):
        t = tot if p.id == ds.id else _totals(db, p)
        history.append({"session_id": p.id, "started_at": p.started_at, "first_mean": t["first_mean"], "best_mean": t["best_mean"]})
    return {"id": ds.id, "kind": ds.kind, "key": ds.key, "label": ds.label, **tot, "history": history}


def recent_sessions(db: Session, limit: int) -> list[dict]:
    out = []
    for ds in db.exec(select(DrillSession).where(DrillSession.ended_at.is_not(None))
                      .order_by(DrillSession.ended_at.desc(), DrillSession.id.desc()).limit(limit)).all():
        t = _totals(db, ds)
        out.append({"id": ds.id, "kind": ds.kind, "key": ds.key, "label": ds.label, "started_at": ds.started_at,
                    "ended_at": ds.ended_at, "first_mean": t["first_mean"], "best_mean": t["best_mean"]})
    return out
