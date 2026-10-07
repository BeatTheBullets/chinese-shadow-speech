"""Repair of forced-alignment spans against coarse character times (addendum spec §1.1).

The Qwen3 aligner predicts boundaries on an 80 ms grid and often returns a zero-length span for a character, or starts
a sentence's first character up to ~1 s before the speech. The coarse times of the same characters (the ASR's, or for
subtitle text the subalign times) are consistent, so a span shorter than MIN_SPAN_S or starting more than
MAX_START_DRIFT_S from its coarse start takes the coarse span (conf REPAIRED_CONF; aligner spans are 1.0, the uniform
fallback 0.0). Spans are then made monotonic, and any span still shorter than MIN_SPAN_S (no coarse time: Anki
segments, or a character an edit added) shares the gap up to the next span with its zero-length neighbours. Finally no
span is left shorter than MIN_SPAN_S (ensure_min_duration)."""
from __future__ import annotations
import logging
from rapidfuzz.distance import Levenshtein
from shadow.ingest.align import Span
from shadow.ingest.text import is_punct
from shadow.ingest.transcript import TimedChar

MIN_SPAN_S = 0.04
MAX_START_DRIFT_S = 0.3
REPAIRED_CONF = 0.5

Times = tuple[float, float]

log = logging.getLogger(__name__)


def coarse_times(text: str, chars: list[TimedChar]) -> list[Times | None]:
    """Per speech character of `text`, the time of the character it lines up with in `chars` (punctuation ignored on
    both sides) under a character edit alignment: equal and substituted characters match, added ones get None."""
    speech = [c for c in text if not is_punct(c)]
    coarse = [c for c in chars if not is_punct(c.c)]
    out: list[Times | None] = [None] * len(speech)
    for op in Levenshtein.opcodes("".join(speech), "".join(c.c for c in coarse)):
        if op.tag in ("equal", "replace"):                  # rapidfuzz replace blocks are 1:1
            for i, j in zip(range(op.src_start, op.src_end), range(op.dest_start, op.dest_end)):
                out[i] = (coarse[j].start, coarse[j].end)
    return out


def make_monotonic(spans: list[Span]) -> list[Span]:
    """Each span starts no earlier than the previous one ends, and ends no earlier than it starts."""
    out: list[Span] = []
    prev_end: float | None = None
    for sp in spans:
        start = sp.start if prev_end is None else max(sp.start, prev_end)
        end = max(sp.end, start)
        out.append(sp if (start, end) == (sp.start, sp.end) else Span(sp.ch, start, end, sp.conf))
        prev_end = end
    return out


def fill_gaps(spans: list[Span]) -> list[Span]:
    """Runs of spans shorter than MIN_SPAN_S share, evenly, the time from the run's start to the next span's start
    (conf REPAIRED_CONF). A run with no later span, or no time before it, is left as it is. Expects monotonic spans."""
    out = list(spans)
    i = 0
    while i < len(out):
        if out[i].end - out[i].start >= MIN_SPAN_S:
            i += 1
            continue
        j = i
        while j + 1 < len(out) and out[j + 1].end - out[j + 1].start < MIN_SPAN_S:
            j += 1
        if j + 1 < len(out) and out[j + 1].start > out[i].start:
            t0, n, t1 = out[i].start, j - i + 1, out[j + 1].start
            step = (t1 - t0) / n
            for m, k in enumerate(range(i, j + 1)):
                out[k] = Span(out[k].ch, t0 + m * step, t1 if m == n - 1 else t0 + (m + 1) * step, REPAIRED_CONF)
        i = j + 1
    return out


def ensure_min_duration(spans: list[Span]) -> list[Span]:
    """No span shorter than MIN_SPAN_S: walking left to right, a shorter span ends MIN_SPAN_S after its start (conf
    REPAIRED_CONF), and each later span starting before the previous end is pushed forward to it (its end at least
    MIN_SPAN_S later). Times stay monotonic, but the last span may now end a few MIN_SPAN_S past the original last end,
    so callers clamp to their clip bounds."""
    out: list[Span] = []
    prev_end: float | None = None
    for sp in spans:
        start = sp.start if prev_end is None else max(sp.start, prev_end)
        end, conf = sp.end, sp.conf
        if end - sp.start < MIN_SPAN_S:
            conf = REPAIRED_CONF
        if end - start < MIN_SPAN_S:
            end = start + MIN_SPAN_S
        out.append(sp if (start, end, conf) == (sp.start, sp.end, sp.conf) else Span(sp.ch, start, end, conf))
        prev_end = end
    return out


def repair_spans(spans: list[Span], coarse: list[Times | None] | None = None) -> list[Span]:
    """`spans` checked against the coarse times of the same characters as the module docstring describes. `coarse`
    None, or of a different length than `spans`, means no coarse times (gap fill only)."""
    if coarse is not None and len(coarse) != len(spans):
        log.warning("coarse times (%d) do not match the spans (%d); ignoring them", len(coarse), len(spans))
        coarse = None
    if coarse is None:
        coarse = [None] * len(spans)
    replaced = [Span(sp.ch, c[0], c[1], REPAIRED_CONF)
                if c is not None and (sp.end - sp.start < MIN_SPAN_S or abs(sp.start - c[0]) > MAX_START_DRIFT_S)
                else sp
                for sp, c in zip(spans, coarse)]
    return ensure_min_duration(fill_gaps(make_monotonic(replaced)))
