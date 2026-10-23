"""Pure score rules for the stats pages: characters, tones and hard sounds. No DB or web imports; callers load rows."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from shadow.ingest.text import is_hanzi
from shadow.scoring.sounds.contrasts import (HARD_DIRECTIONS, checkable_directions_of, direction, direction_label,
                                             heard_pinyin)

MIN_SYLLABLES = 30    # counted syllables for a Tones or Sounds score
MIN_CHARS = 10        # qualifying characters for a Characters score
MIN_CHAR_TAKES = 3    # takes for a character to qualify
MIN_WEAK = 8          # rows for a tone or pair in the weakest list
MIN_CHANCES = 8       # chances for a sound direction
REGRESSED = 0.15      # best - last at or above this is a regression


@dataclass(frozen=True)
class SylRow:
    ch: str
    pinyin: str                 # toneless, lower case
    tone: int                   # coalesce(target_tone, tone)
    prev_tone: int | None
    tone_score: float | None
    status: str                 # ok | close | wrong | missing | unvoiced
    sound_status: str | None
    heard: str | None           # lower case
    created_at: datetime        # aware UTC
    attempt_id: int
    idx: int


@dataclass(frozen=True)
class Score:
    value: float | None
    n: int


def tone_value(r: SylRow) -> float | None:
    if r.status == "unvoiced":
        return None
    if r.status == "missing":
        return 0.0
    return r.tone_score


def char_right(r: SylRow) -> bool | None:
    if r.status == "unvoiced" or not is_hanzi(r.ch) or r.tone not in (1, 2, 3, 4):
        return None
    return r.status == "ok" and r.sound_status != "slip"


def sound_outcome(r: SylRow) -> bool | None:
    if r.sound_status is None or not (checkable_directions_of(r.pinyin) & HARD_DIRECTIONS):
        return None
    if r.sound_status != "slip":
        return True
    d = direction(r.pinyin, r.heard) if r.heard else None
    return False if d in HARD_DIRECTIONS else None


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def tones_score(rows: list[SylRow]) -> Score:
    vals = [v for r in rows if r.tone in (1, 2, 3, 4) and (v := tone_value(r)) is not None]
    return Score(_mean(vals) if len(vals) >= MIN_SYLLABLES else None, len(vals))


def _by_char(rows: list[SylRow]) -> dict[str, list[bool]]:
    out: dict[str, list[bool]] = defaultdict(list)
    for r in rows:
        if (ok := char_right(r)) is not None:
            out[r.ch].append(ok)
    return out


def characters_score(rows: list[SylRow]) -> Score:
    means = [sum(v) / len(v) for v in _by_char(rows).values() if len(v) >= MIN_CHAR_TAKES]
    return Score(_mean(means) if len(means) >= MIN_CHARS else None, len(means))


def sounds_score(rows: list[SylRow]) -> Score:
    outs = [o for r in rows if (o := sound_outcome(r)) is not None]
    return Score(sum(outs) / len(outs) if len(outs) >= MIN_SYLLABLES else None, len(outs))


def score_set(rows: list[SylRow], now: datetime) -> dict:
    last = [r for r in rows if now - timedelta(days=7) <= r.created_at < now]
    prev = [r for r in rows if now - timedelta(days=14) <= r.created_at < now - timedelta(days=7)]
    out = {}
    for name, fn in (("characters", characters_score), ("tones", tones_score), ("sounds", sounds_score)):
        whole = fn(rows)
        out[name] = {"value": whole.value, "last7": fn(last).value, "prev7": fn(prev).value, "n": whole.n}
    return out


def character_stats(rows: list[SylRow]) -> list[dict]:
    by: dict[str, list[SylRow]] = defaultdict(list)
    for r in rows:
        if char_right(r) is not None:
            by[r.ch].append(r)
    out = []
    for ch, rs in by.items():
        if len(rs) < MIN_CHAR_TAKES:
            continue
        rs.sort(key=lambda r: (r.created_at, r.attempt_id, r.idx))
        right = [bool(char_right(r)) for r in rs]
        checked = [r for r in rs if r.sound_status is not None]
        py = Counter(r.pinyin for r in rs).most_common(1)[0][0]
        tone = Counter(r.tone for r in rs).most_common(1)[0][0]
        trend = None
        if len(rs) >= 15:
            trend = sum(right[-10:]) / 10 - sum(right[:-10]) / len(right[:-10])
        out.append({
            "ch": ch, "pinyin": heard_pinyin(py, tone), "score": sum(right) / len(right),
            "tone_right": sum(r.status == "ok" for r in rs) / len(rs),
            "sound_right": (sum(r.sound_status == "ok" for r in checked) / len(checked)) if checked else None,
            "takes": len(rs), "trend": trend,
        })
    out.sort(key=lambda d: (d["score"], -d["takes"], d["ch"]))
    return out


def tone_groups(rows: list[SylRow]) -> tuple[list[dict], list[dict]]:
    tones: dict[int, list[float]] = defaultdict(list)
    pairs: dict[tuple[int, int], list[float]] = defaultdict(list)
    for r in rows:
        v = tone_value(r)
        if v is None:
            continue
        if 0 <= r.tone <= 4:
            tones[r.tone].append(v)
            if r.prev_tone is not None and 0 <= r.prev_tone <= 4:
                pairs[(r.prev_tone, r.tone)].append(v)
    return ([{"tone": t, "mean": _mean(v), "n": len(v)} for t, v in sorted(tones.items())],
            [{"prev_tone": p, "tone": t, "mean": _mean(v), "n": len(v)} for (p, t), v in sorted(pairs.items())])


def weakest_tones(rows: list[SylRow], k: int = 3) -> list[dict]:
    tones, pairs = tone_groups(rows)
    cands = [{"kind": "tone", "key": str(g["tone"]), "label": f"Tone {g['tone']}", "mean": g["mean"], "n": g["n"]}
             for g in tones if g["tone"] != 0 and g["n"] >= MIN_WEAK]
    cands += [{"kind": "pair", "key": f"{g['prev_tone']}-{g['tone']}", "label": f"{g['prev_tone']} → {g['tone']}",
               "mean": g["mean"], "n": g["n"]} for g in pairs if g["prev_tone"] != 0 and g["n"] >= MIN_WEAK]
    cands.sort(key=lambda c: (c["mean"], -c["n"], c["key"]))
    return cands[:k]


def sound_directions(rows: list[SylRow]) -> list[dict]:
    """Every checked syllable is a chance for each checkable direction its pinyin offers; a slip counts for the
    direction actually heard (same semantics as the old /stats/sounds)."""
    tot: dict[str, list[int]] = defaultdict(lambda: [0, 0])      # key -> [slips, chances]
    for r in rows:
        if r.sound_status is None:
            continue
        slip = direction(r.pinyin, r.heard) if r.sound_status == "slip" and r.heard else None
        for key in checkable_directions_of(r.pinyin):
            tot[key][0] += key == slip
            tot[key][1] += 1
    out = [{"key": key, "label": direction_label(key), "slips": s, "chances": c, "rate": s / c,
            "hard": key in HARD_DIRECTIONS} for key, (s, c) in tot.items() if c >= MIN_CHANCES]
    out.sort(key=lambda d: (-d["rate"], -d["chances"], d["key"]))
    return out


def weakest_sounds(rows: list[SylRow], k: int = 3) -> list[dict]:
    return [d for d in sound_directions(rows) if d["hard"] and d["slips"] > 0][:k]


def rank_sentences(rows: list[dict]) -> list[dict]:
    out = [{**r, "regressed": r["best"] - r["last"] >= REGRESSED - 1e-9} for r in rows]
    out.sort(key=lambda r: (not r["regressed"], -(r["best"] - r["last"]) if r["regressed"] else r["last"]))
    return out
