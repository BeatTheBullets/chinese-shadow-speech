"""Subtitles supply the text, ASR supplies the timing (spec §3.2).

The subtitle's speech characters are aligned to the ASR transcript's speech characters with a character-level
edit alignment; each subtitle character takes the time of the ASR character it lines up with."""
from __future__ import annotations
from rapidfuzz.distance import Levenshtein
from shadow.ingest.text import is_punct
from shadow.ingest.transcript import TimedChar, Transcript, append_segment, chars_with_speech_times

# Below this share of subtitle speech chars found in the ASR, the subtitles are taken to be for other audio.
MIN_SUBTITLE_MATCH = 0.5

Times = tuple[float, float]


def _anchor(sub: str, asr: list[TimedChar]) -> tuple[list[Times | None], int]:
    """The ASR (start, end) of each char of `sub` (None when it has no ASR counterpart), and how many chars of
    `sub` equal the ASR char they are aligned with. Substituted chars (e.g. homophones) take the ASR time too;
    ASR chars with no subtitle counterpart are ignored."""
    times: list[Times | None] = [None] * len(sub)
    equal = 0
    for op in Levenshtein.opcodes(sub, "".join(c.c for c in asr)):
        if op.tag in ("equal", "replace"):
            for i, j in zip(range(op.src_start, op.src_end), range(op.dest_start, op.dest_end)):
                times[i] = (asr[j].start, asr[j].end)
            if op.tag == "equal":
                equal += op.src_end - op.src_start
    return times, equal


def _fill(anchored: list[Times | None]) -> list[Times]:
    """Complete `anchored`: anchors are made monotonic (each starts no earlier than the previous one ends), runs
    without an anchor share the gap between their neighbouring anchors evenly, and runs before the first / after
    the last anchor are clamped (zero length) to it. All zero when there is no anchor at all."""
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
        gap = q - p - 1
        lo, hi = out[p][1], out[q][0]
        step = (hi - lo) / max(gap, 1)
        for n in range(gap):
            out[p + 1 + n] = (lo + n * step, hi if n == gap - 1 else lo + (n + 1) * step)
    return out


def align_text_to_asr(pieces: list[str], asr: Transcript) -> tuple[Transcript, float]:
    """A transcript with the characters of `pieces` (one segment per non-empty piece: a cue or a line) timed
    from `asr`, and the match ratio: the share of the pieces' speech chars equal to the ASR char they are aligned
    with. Punctuation gets a zero-length time at the previous char's end. Times are monotonically non-decreasing."""
    asr_speech = [c for c in asr.chars if not is_punct(c.c)]
    sub_speech = "".join(ch for piece in pieces for ch in piece if not is_punct(ch))
    anchored, equal = _anchor(sub_speech, asr_speech)
    times = _fill(anchored)
    tr = Transcript()
    last_end = times[0][0] if times else 0.0
    k = 0
    for piece in pieces:
        n = sum(1 for ch in piece if not is_punct(ch))
        if append_segment(tr, chars_with_speech_times(piece, times[k:k + n], last_end)):
            last_end = tr.chars[-1].end
        k += n
    return tr, (equal / len(sub_speech) if sub_speech else 0.0)
