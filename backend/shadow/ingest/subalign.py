"""Subtitles supply the text, ASR supplies the timing (spec §3.2).

The subtitle's speech characters are aligned to the ASR transcript's speech characters with a character-level
edit alignment (`Levenshtein.opcodes`). Only part of that alignment is trusted, because when the ASR holds speech
the subtitles do not cover (an intro, a song, a passage between cues) an extra ASR character costs the same
wherever it goes, so a lone subtitle character the ASR misheard or dropped can line up with the same character
anywhere in that uncovered speech:

- **Trusted anchors**: characters inside runs of at least `MIN_ANCHOR_RUN` consecutive equal characters. They take
  the ASR character's time.
- **Stretches** between two trusted runs: if the ASR holds at most `MAX_STRETCH_EXTRA` more characters there than
  the subtitles, it is the same speech heard differently, so characters lined up with an ASR character (equal or
  substituted, e.g. homophones) take its time and the rest are interpolated between their timed neighbours. If the
  ASR holds more, it is speech the subtitles do not cover: nothing in the stretch is anchored, and each character
  is pinned (zero length) to the trusted anchor on its own side: the previous one when it belongs to the same cue
  or line, else the next one.
- Text before the first / after the last trusted anchor is pinned to it.

The match ratio is the share of subtitle speech characters inside trusted runs."""
from __future__ import annotations
from dataclasses import dataclass
from rapidfuzz.distance import Levenshtein
from shadow.ingest.text import is_punct
from shadow.ingest.transcript import TimedChar, Transcript, append_segment, chars_with_speech_times

# Below this share of subtitle speech chars in trusted runs, the subtitles are taken to be for other audio.
MIN_SUBTITLE_MATCH = 0.5
# Equal runs shorter than this can be chance matches against speech the subtitles do not cover.
MIN_ANCHOR_RUN = 3
# Between two trusted runs, at most this many more ASR chars than subtitle chars is the same speech heard
# differently (a filler, a split word); more means the ASR heard speech the subtitles do not cover.
MAX_STRETCH_EXTRA = 2

Times = tuple[float, float]


@dataclass
class SubtitleAlignment:
    transcript: Transcript   # the subtitle text, timed from the ASR
    matched: int             # subtitle speech chars inside trusted runs
    total: int               # subtitle speech chars

    @property
    def ratio(self) -> float:
        return self.matched / self.total if self.total else 0.0


def _anchor(sub: str, asr: list[TimedChar], piece_of: list[int]) -> tuple[list[Times | None], list[int], int]:
    """For each char of `sub`: its ASR time when anchored (else None), and for chars of a stretch the subtitles do
    not cover, the side it is pinned to (-1 previous / +1 next trusted anchor, else 0); plus the trusted count."""
    n = len(sub)
    asr_index: list[int | None] = [None] * n
    trusted: list[int] = []
    for op in Levenshtein.opcodes(sub, "".join(c.c for c in asr)):
        if op.tag in ("equal", "replace"):             # rapidfuzz replace blocks are 1:1
            for i, j in zip(range(op.src_start, op.src_end), range(op.dest_start, op.dest_end)):
                asr_index[i] = j
            if op.tag == "equal" and op.src_end - op.src_start >= MIN_ANCHOR_RUN:
                trusted.extend(range(op.src_start, op.src_end))

    def time_of(i: int) -> Times:
        c = asr[asr_index[i]]
        return (c.start, c.end)

    times: list[Times | None] = [None] * n
    side = [0] * n
    for i in trusted:
        times[i] = time_of(i)
    for p, q in zip(trusted, trusted[1:]):
        if q == p + 1:
            continue
        if (asr_index[q] - asr_index[p]) - (q - p) <= MAX_STRETCH_EXTRA:
            for i in range(p + 1, q):
                if asr_index[i] is not None:
                    times[i] = time_of(i)
        else:
            for i in range(p + 1, q):
                side[i] = -1 if piece_of[i] == piece_of[p] else 1
    return times, side, len(trusted)


def _fill(anchored: list[Times | None], side: list[int]) -> list[Times]:
    """Complete `anchored`: anchors are made monotonic (each starts no earlier than the previous one ends); between
    two anchors, chars with a `side` are pinned (zero length) to that neighbour and the others share the gap
    evenly; chars before the first / after the last anchor are pinned to it. All zero when nothing is anchored."""
    out: list[Times] = [(0.0, 0.0)] * len(anchored)
    anchors: list[int] = []
    prev_end = None
    for k, t in enumerate(anchored):
        if t is None:
            continue
        s = t[0] if prev_end is None else max(t[0], prev_end)
        out[k] = (s, max(t[1], s))
        prev_end = out[k][1]
        anchors.append(k)
    if not anchors:
        return out
    first, last = anchors[0], anchors[-1]
    for k in range(first):
        out[k] = (out[first][0], out[first][0])
    for k in range(last + 1, len(out)):
        out[k] = (out[last][1], out[last][1])
    for p, q in zip(anchors, anchors[1:]):
        lo, hi = out[p][1], out[q][0]
        free = [k for k in range(p + 1, q) if side[k] == 0]
        for k in range(p + 1, q):
            if side[k]:
                out[k] = (lo, lo) if side[k] < 0 else (hi, hi)
        step = (hi - lo) / max(len(free), 1)
        for m, k in enumerate(free):
            out[k] = (lo + m * step, hi if m == len(free) - 1 else lo + (m + 1) * step)
    return out


def align_text_to_asr(pieces: list[str], asr: Transcript) -> SubtitleAlignment:
    """The characters of `pieces` (one segment per non-empty piece: a cue or a line) timed from `asr` as described
    in the module docstring. Punctuation gets a zero-length time at the previous char's end. Times are
    monotonically non-decreasing."""
    asr_speech = [c for c in asr.chars if not is_punct(c.c)]
    sub_speech, piece_of = [], []
    for n, piece in enumerate(pieces):
        for ch in piece:
            if not is_punct(ch):
                sub_speech.append(ch)
                piece_of.append(n)
    anchored, side, matched = _anchor("".join(sub_speech), asr_speech, piece_of)
    times = _fill(anchored, side)
    tr = Transcript()
    last_end = times[0][0] if times else 0.0
    k = 0
    for piece in pieces:
        n = sum(1 for ch in piece if not is_punct(ch))
        if append_segment(tr, chars_with_speech_times(piece, times[k:k + n], last_end)):
            last_end = tr.chars[-1].end
        k += n
    return SubtitleAlignment(tr, matched, len(sub_speech))
