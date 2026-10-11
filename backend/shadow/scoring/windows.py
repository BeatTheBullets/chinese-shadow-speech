"""Syllable windows (Phase 2 spec §10.1): MMS (CTC) spans stop at the last letter's peak, about half-way through
the syllable; pitch, embeddings and the contour overlay use the window up to where the next syllable starts."""
from __future__ import annotations

MAX_EXT = 0.5            # a window runs to the next start only if that is at most this far after its own start
TAIL = 0.15              # otherwise (a pause, or the last syllable) it ends this far after its span


def windows(spans: list[tuple[float, float]], dur: float) -> list[tuple[float, float]]:
    out = []
    for i, (a, b) in enumerate(spans):
        nxt = spans[i + 1][0] if i + 1 < len(spans) else None
        if nxt is not None and nxt <= max(b, a + MAX_EXT):
            e = nxt
        else:
            e = min(b + TAIL, nxt if nxt is not None else dur, dur)
        out.append((a, max(e, b)))
    return out
