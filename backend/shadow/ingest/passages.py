"""Passages (addendum spec §4): contiguous runs of segments of about 2–3 minutes, the unit of Flow runs and progress.

Boundaries come from the video's chapters when it has them (a chapter longer than SPLIT_CHAPTER_OVER_S is split like
a lesson); otherwise from a greedy cut: from a passage's first segment, cut before the segment starting CUT_WINDOW
after it with the longest pause before it (ties: the cut nearest TARGET_S), never leaving a last passage shorter than
MIN_LAST_S. A lesson shorter than ONE_PASSAGE_UNDER_S is one passage, chapters or not. Rows store only the time
range; a segment belongs to the last passage starting at or before its start_s (the first when it starts before them
all), so edits never break the mapping."""
from __future__ import annotations
from bisect import bisect_right
from dataclasses import dataclass, field
from sqlalchemy import Engine
from sqlmodel import Session, select
from shadow.store.models import Lesson, Passage, Segment

TARGET_S = 150.0
CUT_WINDOW = (120.0, 180.0)
MIN_LAST_S = 60.0
ONE_PASSAGE_UNDER_S = 240.0
SPLIT_CHAPTER_OVER_S = 240.0

Bounds = tuple[float, float]


@dataclass
class PassagePlan:
    start_s: float
    end_s: float
    title: str | None = None          # None: default_title()


@dataclass
class PassageView:
    idx: int
    title: str
    start_s: float
    end_s: float
    segment_ids: list[int] = field(default_factory=list)
    done: bool = False


def _mmss(t: float) -> str:
    t = max(0, int(t))
    return f"{t // 60:02d}:{t % 60:02d}"


def default_title(i: int, start_s: float, end_s: float) -> str:
    return f"Passage {i + 1} · {_mmss(start_s)}–{_mmss(end_s)}"


def _greedy(segs: list[Bounds]) -> list[list[int]]:
    """Indices of `segs` (ordered by start) per passage."""
    groups: list[list[int]] = []
    a, n, end = 0, len(segs), max(b for _, b in segs)
    lo, hi = CUT_WINDOW
    while a < n:
        t0 = segs[a][0]
        if a == 0 and end - t0 < ONE_PASSAGE_UNDER_S:
            cut = n
        else:
            fits = [k for k in range(a + 1, n) if lo <= segs[k][0] - t0 <= hi and end - segs[k][0] >= MIN_LAST_S]
            if fits:
                cut = max(fits, key=lambda k: (round(segs[k][0] - segs[k - 1][1], 3), -abs(segs[k][0] - t0 - TARGET_S)))
            elif end - t0 <= hi + MIN_LAST_S:
                cut = n                   # the rest is one passage; a short remainder is absorbed
            else:
                later = [k for k in range(a + 1, n) if segs[k][0] - t0 > hi and end - segs[k][0] >= MIN_LAST_S]
                cut = later[0] if later else n
        groups.append(list(range(a, cut)))
        a = cut
    return groups


def plan_passages(segs: list[Bounds], chapters: list[dict] | None = None) -> list[PassagePlan]:
    """Passages over `segs` ((start_s, end_s), ordered by start); titles only from chapters."""
    if not segs:
        return []
    end = max(b for _, b in segs)
    if end - segs[0][0] < ONE_PASSAGE_UNDER_S:
        return [PassagePlan(segs[0][0], end)]
    if not chapters:
        return [PassagePlan(segs[g[0]][0], max(segs[k][1] for k in g)) for g in _greedy(segs)]
    plans: list[PassagePlan] = []
    chs = sorted(chapters, key=lambda c: c["start_time"])
    for n, ch in enumerate(chs):
        lo = ch["start_time"] if n else float("-inf")           # speech before the first chapter joins it
        hi = chs[n + 1]["start_time"] if n + 1 < len(chs) else float("inf")
        mine = [s for s in segs if lo <= s[0] < hi]
        if not mine:
            continue
        title = ch.get("title") or None
        if ch["end_time"] - ch["start_time"] > SPLIT_CHAPTER_OVER_S:
            groups = _greedy(mine)
            for m, g in enumerate(groups):
                plans.append(PassagePlan(mine[g[0]][0], max(mine[k][1] for k in g),
                                         f"{title} ({m + 1}/{len(groups)})" if title else None))
        else:
            plans.append(PassagePlan(mine[0][0], max(b for _, b in mine), title))
    return plans


def plan_for(lesson: Lesson, segs: list[Segment]) -> list[PassagePlan]:
    """The lesson's passages from its segments (and YouTube chapters), every title filled in."""
    bounds = sorted((s.start_s, s.end_s) for s in segs)
    plans = plan_passages(bounds, (lesson.meta_json or {}).get("chapters"))
    return [PassagePlan(p.start_s, p.end_s, p.title or default_title(i, p.start_s, p.end_s)) for i, p in enumerate(plans)]


def rebuild_passages(engine: Engine, lesson_id: int) -> None:
    """Replace the lesson's Passage rows with a fresh plan (after ingest, resplit and merge); no-op for a deleted lesson."""
    with Session(engine) as db:
        lesson = db.get(Lesson, lesson_id)
        if lesson is None:
            return
        segs = db.exec(select(Segment).where(Segment.lesson_id == lesson_id)).all()
        for row in db.exec(select(Passage).where(Passage.lesson_id == lesson_id)).all():
            db.delete(row)
        for i, p in enumerate(plan_for(lesson, segs)):
            db.add(Passage(lesson_id=lesson_id, idx=i, title=p.title, start_s=p.start_s, end_s=p.end_s))
        db.commit()


def passage_index(starts: list[float], seg_start: float) -> int:
    """Index of the passage (by ascending `starts`) a segment starting at `seg_start` belongs to."""
    return max(bisect_right(starts, seg_start) - 1, 0)


def passage_views(plans: list[PassagePlan], segs: list[tuple[int, float, int]]) -> list[PassageView]:
    """`plans` (ordered by start) with their members: `segs` are (segment id, start_s, attempts) in lesson order. A
    passage is done when it has segments and every one has an attempt."""
    if not plans:
        return []
    starts = [p.start_s for p in plans]
    views = [PassageView(i, p.title or default_title(i, p.start_s, p.end_s), p.start_s, p.end_s, [], True)
             for i, p in enumerate(plans)]
    for sid, start, attempts in segs:
        v = views[passage_index(starts, start)]
        v.segment_ids.append(sid)
        v.done = v.done and attempts > 0
    for v in views:
        v.done = v.done and bool(v.segment_ids)
    return views
