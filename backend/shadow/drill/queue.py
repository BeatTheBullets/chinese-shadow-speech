"""The drill queue (Phase 3b spec §2): sentences from every ready lesson that contain the focus."""
from __future__ import annotations
from sqlmodel import Session, select
from shadow.api.lessons import _attempt_stats
from shadow.config import DrillCfg
from shadow.scoring.reference import segment_syllables
from shadow.store.models import Attempt, DrillSession, Lesson, Segment, SyllableScore


def targets_for(syllables: list[dict], kind: str, key: str) -> list[int]:
    """Indexes of the syllables the focus is about, by canonical tone (good enough for picking sentences)."""
    if kind == "tone":
        return [i for i, s in enumerate(syllables) if str(s["tone"]) == key]
    if kind == "pair":
        p, t = key.split("-")
        return [i for i in range(1, len(syllables))
                if str(syllables[i - 1]["tone"]) == p and str(syllables[i]["tone"]) == t]
    return [i for i, s in enumerate(syllables) if s["ch"] == key]


def went_green(db: Session, drill_session_id: int, segment_id: int, targets: list[int]) -> bool:
    """Some drill take of this sentence in that session had every target syllable ok."""
    atts = db.exec(select(Attempt.id).where(Attempt.drill_session_id == drill_session_id,
                                            Attempt.segment_id == segment_id)).all()
    for aid in atts:
        rows = {r.idx: r.status for r in db.exec(select(SyllableScore).where(SyllableScore.attempt_id == aid)).all()}
        if targets and all(rows.get(i) == "ok" for i in targets):
            return True
    return False


def _recent_green(db: Session, kind: str, key: str) -> set[int]:
    sessions = db.exec(select(DrillSession).where(DrillSession.kind == kind, DrillSession.key == key)
                       .order_by(DrillSession.started_at.desc(), DrillSession.id.desc()).limit(2)).all()
    out = set()
    for ds in sessions:
        for it in ds.items_json or []:
            if went_green(db, ds.id, it["segment_id"], it["targets"]):
                out.add(it["segment_id"])
    return out


def _candidates(db: Session, cfg: DrillCfg, kind: str, key: str) -> list[tuple[Segment, list[int]]]:
    q = (select(Segment).join(Lesson, Lesson.id == Segment.lesson_id)
         .where(Lesson.status == "ready", Segment.words_json.is_not(None), Segment.clip_wav_path.is_not(None)))
    out = []
    for s in db.exec(q).all():
        syl = segment_syllables(s)
        if cfg.min_syllables <= len(syl) <= cfg.max_syllables and (t := targets_for(syl, kind, key)):
            out.append((s, t))
    return out


def build_queue(db: Session, cfg: DrillCfg, kind: str, key: str) -> list[tuple[Segment, list[int]]]:
    skip = _recent_green(db, kind, key)
    every = _candidates(db, cfg, kind, key)
    # All of them went green lately: drill them again rather than 404 a focus that has sentences (the auto pick
    # would keep offering it, and no session means its rotation never moves on).
    cands = [(s, t) for s, t in every if s.id not in skip] or every
    stats = _attempt_stats(db, Segment.id.in_([s.id for s, _ in cands])) if cands else {}

    def rank(item):
        s, t = item
        n, last, _ = stats.get(s.id, (0, None, None))
        practised = 2 * (1 - last) if last is not None else (1.0 if n == 0 else 0.0)
        return (-(2 * min(len(t), 3) + practised), s.id)

    ranked = sorted(cands, key=rank)
    taken, deferred, per_lesson = [], [], {}
    for item in ranked:
        if len(taken) == cfg.queue_size:
            break
        lid = item[0].lesson_id
        if per_lesson.get(lid, 0) < cfg.max_per_lesson:
            taken.append(item); per_lesson[lid] = per_lesson.get(lid, 0) + 1
        else:
            deferred.append(item)
    taken += deferred[: cfg.queue_size - len(taken)]          # only lessons without more material left: fill up
    return sorted(taken, key=lambda it: (it[0].lesson_id, it[0].idx))


def queue_from_ids(db: Session, segment_ids: list[int], kind: str, key: str) -> list[tuple[Segment, list[int]]]:
    out = []
    for sid in segment_ids:
        s = db.get(Segment, sid)
        if s is not None and (t := targets_for(segment_syllables(s), kind, key)):
            out.append((s, t))
    return out
