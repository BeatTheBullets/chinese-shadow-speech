"""Drill focuses (Phase 3b spec §1): which tone, tone pair or character is weakest in the recent scores."""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from sqlmodel import Session, select
from shadow.config import DrillCfg
from shadow.drill.summary import HAS_TAKES
from shadow.ingest.text import is_hanzi
from shadow.store.models import Attempt, DrillSession, SyllableScore

TONE_NAMES = {1: "high", 2: "rising", 3: "low", 4: "falling"}
_KIND_ORDER = {"tone": 0, "pair": 1, "char": 2}


@dataclass
class Focus:
    kind: str
    key: str
    label: str
    mean: float
    n: int


def focus_label(kind: str, key: str, pinyin: str | None = None) -> str:
    if kind == "tone":
        return f"tone {key} ({TONE_NAMES[int(key)]})"
    if kind == "pair":
        p, t = key.split("-")
        return f"tone pair {p}→{t}"
    return f"{key} {pinyin}" if pinyin else key


def rank_focuses(db: Session, cfg: DrillCfg, now: datetime | None = None) -> list[Focus]:
    """Qualifying focuses, weakest first. Missing syllables count 0 (as the sentence score does); unvoiced ones say
    nothing about tone and are left out."""
    since = (now or datetime.now(timezone.utc)) - timedelta(days=cfg.window_days)
    q = (select(SyllableScore.ch, SyllableScore.pinyin_toneless, SyllableScore.tone, SyllableScore.target_tone,
                SyllableScore.prev_tone, SyllableScore.tone_score, SyllableScore.status, SyllableScore.segment_id)
         .join(Attempt, Attempt.id == SyllableScore.attempt_id)
         .where(Attempt.created_at >= since, SyllableScore.status != "unvoiced"))
    scores: dict[tuple[str, str], list[float]] = defaultdict(list)
    sentences: dict[str, set[int]] = defaultdict(set)
    pinyin: dict[str, str] = {}
    for ch, py, tone, target, prev, score, status, seg_id in db.exec(q).all():
        v = 0.0 if status == "missing" else score
        if v is None:
            continue
        t = target if target is not None else tone
        if t in TONE_NAMES:
            scores[("tone", str(t))].append(v)
            if prev in TONE_NAMES:
                scores[("pair", f"{prev}-{t}")].append(v)
        if is_hanzi(ch):
            scores[("char", ch)].append(v)
            sentences[ch].add(seg_id)
            pinyin.setdefault(ch, py)
    out = []
    for (kind, key), vals in scores.items():
        if len(vals) < cfg.min_rows or (kind == "char" and len(sentences[key]) < 2):
            continue
        out.append(Focus(kind, key, focus_label(kind, key, pinyin.get(key)), sum(vals) / len(vals), len(vals)))
    return sorted(out, key=lambda f: (f.mean, -f.n, _KIND_ORDER[f.kind], f.key))


def auto_focus(db: Session, focuses: list[Focus], cfg: DrillCfg) -> Focus | None:
    """The weakest focus — unless the last finished drill had it and the next one is about as weak (rotation)."""
    if not focuses:
        return None
    last = db.exec(select(DrillSession).where(DrillSession.ended_at.is_not(None), HAS_TAKES)
                   .order_by(DrillSession.ended_at.desc(), DrillSession.id.desc())).first()
    first = focuses[0]
    if (last is not None and (last.kind, last.key) == (first.kind, first.key) and len(focuses) > 1
            and focuses[1].mean - first.mean <= cfg.rotate_within):
        return focuses[1]
    return first
