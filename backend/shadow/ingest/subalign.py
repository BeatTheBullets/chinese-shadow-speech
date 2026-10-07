"""Subtitles supply the text, ASR supplies the timing (spec §3.2).

The subtitle's speech characters are aligned to the ASR transcript's speech characters with a character-level
edit alignment (`Levenshtein.opcodes`). Only part of that alignment is trusted, because when the ASR holds speech
the subtitles do not cover (an intro, a song, a passage between cues) an extra ASR character costs the same
wherever it goes, so a lone subtitle character the ASR misheard or dropped can line up with the same character
anywhere in that uncovered speech, or be stretched over a silence:

- **Trusted anchors**: characters inside runs of at least `MIN_ANCHOR_RUN` consecutive equal characters within one
  piece (cue or plain-text line); runs are split at piece boundaries first, so an edge character cannot join the
  next cue's run across uncovered speech. They take the ASR character's time.
- **Stretches** between two trusted runs are *covered* when the ASR holds at most `MAX_STRETCH_EXTRA` more
  characters there than the subtitles and no silence longer than `MAX_SILENCE_S` (between the trusted anchors and
  the ASR characters in between): the same speech heard differently. There, characters lined up with an ASR
  character (equal or substituted, e.g. homophones) take its time. Otherwise nothing in the stretch is anchored.
- Every other character is placed between its neighbouring anchors: interpolated evenly when both neighbours are in
  its piece and the stretch is covered; else pinned (zero length) to the neighbour in its own piece (the nearer one
  when both are, the next one when neither is). Nothing is ever interpolated across a piece boundary or an uncovered stretch.
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
# A longer silence between two trusted runs (music, a pause the ASR heard nothing in) is not spread over the
# subtitle characters in between.
MAX_SILENCE_S = 2.0

Times = tuple[float, float]


@dataclass
class SubtitleAlignment:
    transcript: Transcript   # the subtitle text, timed from the ASR
    matched: int             # subtitle speech chars inside trusted runs
    total: int               # subtitle speech chars

    @property
    def ratio(self) -> float:
        return self.matched / self.total if self.total else 0.0


def _runs_by_piece(start: int, end: int, piece_of: list[int]) -> list[range]:
    """`range(start, end)` split where the piece changes."""
    runs, a = [], start
    for i in range(start + 1, end + 1):
        if i == end or piece_of[i] != piece_of[a]:
            runs.append(range(a, i))
            a = i
    return runs


def _covered(asr: list[TimedChar], j0: int, j1: int, sub_count: int) -> bool:
    """Whether ASR chars j0 < … < j1 (two trusted anchors and the chars between them) are the same speech as the
    `sub_count` subtitle chars between those anchors: few extra ASR chars and no long silence."""
    if (j1 - j0 - 1) - sub_count > MAX_STRETCH_EXTRA:
        return False
    return all(asr[j + 1].start - asr[j].end <= MAX_SILENCE_S for j in range(j0, j1))


def _anchor(sub: str, asr: list[TimedChar], piece_of: list[int]) -> tuple[list[Times | None], list[bool], int]:
    """For each char of `sub`: its ASR time when anchored (else None) and whether it lies in a covered stretch
    (may be interpolated); plus the number of trusted chars."""
    n = len(sub)
    asr_index: list[int | None] = [None] * n
    trusted: list[int] = []
    for op in Levenshtein.opcodes(sub, "".join(c.c for c in asr)):
        if op.tag in ("equal", "replace"):             # rapidfuzz replace blocks are 1:1
            for i, j in zip(range(op.src_start, op.src_end), range(op.dest_start, op.dest_end)):
                asr_index[i] = j
            if op.tag == "equal":
                for run in _runs_by_piece(op.src_start, op.src_end, piece_of):
                    if len(run) >= MIN_ANCHOR_RUN:
                        trusted.extend(run)

    def time_of(i: int) -> Times:
        c = asr[asr_index[i]]
        return (c.start, c.end)

    times: list[Times | None] = [None] * n
    covered = [False] * n
    for i in trusted:
        times[i] = time_of(i)
    for p, q in zip(trusted, trusted[1:]):
        if q > p + 1 and _covered(asr, asr_index[p], asr_index[q], q - p - 1):
            for i in range(p + 1, q):
                covered[i] = True
                if asr_index[i] is not None:
                    times[i] = time_of(i)
    return times, covered, len(trusted)


def _fill(anchored: list[Times | None], covered: list[bool], piece_of: list[int]) -> list[Times]:
    """Complete `anchored`: anchors are made monotonic (each starts no earlier than the previous one ends); a char
    between two anchors is interpolated when it is in a covered stretch and in the same piece as both, else pinned
    (zero length) to the anchor in its own piece (the nearer one when both are, the next one when neither is); chars
    before the first / after the last anchor are pinned to it. All zero when nothing is anchored."""
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
        free = []
        for k in range(p + 1, q):
            one_piece = piece_of[p] == piece_of[k] == piece_of[q]
            if one_piece and covered[k]:
                free.append(k)
            elif piece_of[k] == piece_of[p] and (not one_piece or k - p <= q - k):
                out[k] = (lo, lo)
            else:
                out[k] = (hi, hi)
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
    anchored, covered, matched = _anchor("".join(sub_speech), asr_speech, piece_of)
    times = _fill(anchored, covered, piece_of)
    tr = Transcript()
    last_end = times[0][0] if times else 0.0
    k = 0
    for piece in pieces:
        n = sum(1 for ch in piece if not is_punct(ch))
        if append_segment(tr, chars_with_speech_times(piece, times[k:k + n], last_end)):
            last_end = tr.chars[-1].end
        k += n
    return SubtitleAlignment(tr, matched, len(sub_speech))
