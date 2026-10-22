from __future__ import annotations
import jieba
from shadow.config import SegmentationCfg
from shadow.ingest.transcript import TimedChar

jieba.setLogLevel(60)


def pause_ranges(chars: list[TimedChar], cfg: SegmentationCfg) -> list[tuple[int, int]]:
    """(first, last) char index per sentence, cut from the recogniser's char times when the text has no punctuation.
    The ranges are contiguous and cover every index. A cut after char k is allowed unless k is inside a jieba word.
    1. cut at every allowed pause >= pause_cut_s; 2. split pieces longer than max_chars at their largest pause
    (preferring pauses >= pause_split_s, leaving >= min_chars each side; ties go nearest the middle); 3. merge
    pieces shorter than min_chars into the neighbour across the smaller pause."""
    n = len(chars)
    if n == 0:
        return []
    allowed = [False] * n                       # allowed[k]: a boundary after char k is not inside a word
    pos = 0
    for word in jieba.cut("".join(ch.c for ch in chars)):
        pos += len(word)
        allowed[pos - 1] = True
    allowed[n - 1] = True
    gap = [round(chars[k + 1].start - chars[k].end, 3) for k in range(n - 1)]    # whole ms: 0.49999999 is 0.5

    ends = [k for k in range(n - 1) if allowed[k] and gap[k] >= cfg.pause_cut_s]
    ends.append(n - 1)

    out: list[int] = []
    a = 0
    for e in ends:                              # step 2, per piece
        stack = [(a, e)]
        while stack:
            lo, hi = stack.pop()
            cut = _split_point(lo, hi, allowed, gap, cfg) if hi - lo + 1 > cfg.max_chars else None
            if cut is None:
                out.append(hi)
            else:
                stack.append((cut + 1, hi))
                stack.append((lo, cut))
        a = e + 1

    while len(out) > 1:                         # step 3
        starts = [0] + [e + 1 for e in out[:-1]]
        short = next((i for i, e in enumerate(out) if e - starts[i] + 1 < cfg.min_chars), None)
        if short is None:
            break
        left = gap[out[short - 1]] if short > 0 else None
        right = gap[out[short]] if short < len(out) - 1 else None
        if right is None or (left is not None and left <= right):
            del out[short - 1]                  # join with the previous piece
        else:
            del out[short]                      # join with the next piece

    return [(([0] + [e + 1 for e in out[:-1]])[i], e) for i, e in enumerate(out)]


def _split_point(lo: int, hi: int, allowed: list[bool], gap: list[float], cfg: SegmentationCfg) -> int | None:
    """The char after which to cut the too-long piece lo..hi, or None when no cut is allowed."""
    mid = (lo + hi) / 2
    inside = [k for k in range(lo, hi) if allowed[k]]
    roomy = [k for k in inside if k - lo + 1 >= cfg.min_chars and hi - k >= cfg.min_chars]
    pauses = [k for k in roomy if gap[k] >= cfg.pause_split_s]
    pool = pauses or roomy or inside
    if not pool:
        return None
    return max(pool, key=lambda k: (gap[k], -abs(k + 0.5 - mid)))
