"""Sentence-splitting gate (laptop-fit plan, Task 4): scores a splitter's cut times against the breaks a human
subtitle author made. A cut's time is the end of the speech character before it; cuts match a human break within
`tol` seconds, one to one."""
from __future__ import annotations
from dataclasses import dataclass
import jieba
from shadow.ingest.text import is_punct
from shadow.ingest.transcript import TimedChar, Transcript

jieba.setLogLevel(60)

FULL_STOPS = set("。！？")


@dataclass
class SplitReport:
    precision: float
    recall: float
    f1: float
    end_recall: float
    pieces: int
    over_25: int
    over_30: int
    under_4: int
    inside_word: int


def _speech_end_before(chars: list[TimedChar], i: int) -> float | None:
    """End of the last speech char at or before index i, or None when there is none."""
    for k in range(i, -1, -1):
        if not is_punct(chars[k].c):
            return chars[k].end
    return None


def piece_ends(chars: list[TimedChar], ranges: list[tuple[int, int]]) -> list[float]:
    """End time of each piece but the last."""
    out = []
    for _, b in ranges[:-1]:
        t = _speech_end_before(chars, b)
        if t is not None:
            out.append(t)
    return out


def reference_breaks(tr: Transcript) -> tuple[list[float], list[float]]:
    """(all human breaks, sentence-end breaks) of a subtitle transcript (one segment per cue): every cue end and every
    punctuation run inside a cue; sentence ends are the 。！？ positions when the text holds any, else the cue ends.
    The break at the very end of the speech is dropped (a splitter has no cut there)."""
    chars = tr.chars
    last_speech = max((i for i, c in enumerate(chars) if not is_punct(c.c)), default=-1)
    cue_idx = {b for _, b in tr.segments}
    mark_idx: set[int] = set()
    stop_idx: set[int] = set()
    for a, b in tr.segments:
        i = a
        while i <= b:
            if is_punct(chars[i].c):
                j = i
                while j + 1 <= b and is_punct(chars[j + 1].c):
                    j += 1
                mark_idx.add(i - 1)                  # the char before the run (its speech end is used)
                if any(chars[k].c in FULL_STOPS for k in range(i, j + 1)):
                    stop_idx.add(i - 1)
                i = j
            i += 1

    def times(idx: set[int]) -> list[float]:
        out = set()
        for i in idx:
            if 0 <= i:
                t = _speech_end_before(chars, i)
                if t is not None and any(not is_punct(chars[k].c) for k in range(i + 1, last_speech + 1)):
                    out.add(t)                       # something is still spoken after this break
        return sorted(out)

    has_stops = any(c.c in FULL_STOPS for c in chars)
    return times(mark_idx | cue_idx), times(stop_idx if has_stops else cue_idx)


def match(pred: list[float], ref: list[float], tol: float = 0.3) -> tuple[int, int, int]:
    """(tp, fp, fn): greedy one-to-one, nearest pairs first, within `tol`."""
    pairs = sorted((abs(p - r), i, j) for i, p in enumerate(pred) for j, r in enumerate(ref) if abs(p - r) <= tol)
    used_p: set[int] = set()
    used_r: set[int] = set()
    for _, i, j in pairs:
        if i not in used_p and j not in used_r:
            used_p.add(i)
            used_r.add(j)
    tp = len(used_p)
    return tp, len(pred) - tp, len(ref) - tp


def _ratio(a: float, b: float) -> float:
    return a / b if b else 0.0


def split_report(chars: list[TimedChar], ranges: list[tuple[int, int]],
                 ref_all: list[float], ref_ends: list[float]) -> SplitReport:
    pred = piece_ends(chars, ranges)
    tp, fp, fn = match(pred, ref_all)
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    f1 = _ratio(2 * precision * recall, precision + recall)
    etp, _, efn = match(pred, ref_ends)
    speech = [c.c for c in chars if not is_punct(c.c)]
    in_word = [False] * len(speech)             # in_word[k]: a cut after speech char k is inside a jieba word
    pos = 0
    for word in jieba.cut("".join(speech)):
        in_word[pos:pos + len(word) - 1] = [True] * (len(word) - 1)
        pos += len(word)
    rank, n = [0] * len(chars), 0               # speech chars up to and including each char
    for i, c in enumerate(chars):
        n += not is_punct(c.c)
        rank[i] = n
    lengths = [rank[b] - (rank[a - 1] if a else 0) for a, b in ranges]
    inside = sum(1 for _, b in ranges[:-1] if rank[b] and in_word[rank[b] - 1])
    return SplitReport(precision, recall, f1, _ratio(etp, etp + efn), len(ranges),
                       sum(n > 25 for n in lengths), sum(n > 30 for n in lengths), sum(n < 4 for n in lengths), inside)


def gate_passes(punc: SplitReport, pauses: SplitReport) -> bool:
    """Pause splitting is at least as good as punctuation splitting on F1 and sentence-end recall, and cuts no piece
    over 30 characters."""
    return pauses.f1 >= punc.f1 and pauses.end_recall >= punc.end_recall and pauses.over_30 == 0
