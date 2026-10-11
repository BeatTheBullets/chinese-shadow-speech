"""Per-syllable contours and classifier features (Phase 2 spec §1 step 6, §4.2). The app and the training tool both
call these; any change to what they return must bump FEATURE_VERSION and retrain the tone model."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from shadow.scoring.embed import DIM
from shadow.scoring.pitch import STEP_S

FEATURE_VERSION = 2
POINTS = 20
NEIGHBOUR_POINTS = 5
TRIM = 0.15
_OWN = POINTS + 6 + 3                    # contour, its summary, voiced ratio / relative duration / position
_NEIGHBOUR = NEIGHBOUR_POINTS + 3        # 5-point contour, mean, voiced ratio, present flag
N_PITCH = _OWN + 2 * _NEIGHBOUR
N_FEATURES = 3 * DIM + 2 + N_PITCH         # own, previous (+flag), next (+flag) embeddings, then the pitch features


@dataclass
class SylPitch:
    contour: np.ndarray | None           # POINTS normalised values; None when unvoiced
    voiced_ratio: float
    duration: float


def syllable_pitch(norm: np.ndarray, t0: float, start: float, end: float, min_voiced: int) -> SylPitch:
    """The syllable's [start, end] with 15 % trimmed at each end, its voiced frames interpolated to POINTS values."""
    dur = max(end - start, 0.0)
    a, b = start + TRIM * dur, end - TRIM * dur
    times = t0 + STEP_S * np.arange(len(norm))
    sel = (times >= a) & (times <= b)
    seg, t = norm[sel], times[sel]
    ok = np.isfinite(seg)
    ratio = float(ok.mean()) if len(seg) else 0.0
    if ok.sum() < min_voiced:
        return SylPitch(None, ratio, dur)
    return SylPitch(np.interp(np.linspace(a, b, POINTS), t[ok], seg[ok]), ratio, dur)


def _summary(c: np.ndarray) -> list[float]:
    h, x = POINTS // 2, np.arange(POINTS // 2)
    return [float(c.mean()), float(np.polyfit(x, c[:h], 1)[0]), float(np.polyfit(x, c[h:], 1)[0]),
            float(c.min()), float(c.max()), float(np.argmin(c)) / (POINTS - 1)]


def _neighbour(s: SylPitch | None) -> list[float]:
    if s is None:
        return [0.0] * _NEIGHBOUR
    if s.contour is None:
        return [0.0] * NEIGHBOUR_POINTS + [0.0, s.voiced_ratio, 1.0]
    pts = np.interp(np.linspace(0, POINTS - 1, NEIGHBOUR_POINTS), np.arange(POINTS), s.contour)
    return [*pts.tolist(), float(s.contour.mean()), s.voiced_ratio, 1.0]


def pitch_matrix(sylls: list[SylPitch]) -> np.ndarray:
    """One row per syllable. Unvoiced syllables get a zero contour."""
    n = len(sylls)
    mean_dur = float(np.mean([s.duration for s in sylls])) if n else 1.0
    rows = []
    for i, s in enumerate(sylls):
        c = s.contour if s.contour is not None else np.zeros(POINTS)
        own = [*c.tolist(), *_summary(c), s.voiced_ratio, s.duration / (mean_dur or 1.0), i / max(n - 1, 1)]
        rows.append(own + _neighbour(sylls[i - 1] if i > 0 else None) + _neighbour(sylls[i + 1] if i < n - 1 else None))
    return np.asarray(rows, dtype=np.float32).reshape(n, N_PITCH)


def feature_matrix(sylls: list[SylPitch], pooled: np.ndarray) -> np.ndarray:
    """The classifier's rows (spec §10): each syllable's pooled embedding, its neighbours' with presence flags,
    and its pitch features. Missing neighbours are zeros with flag 0."""
    n = len(sylls)
    zero = np.zeros(DIM, np.float32)
    P = pitch_matrix(sylls)
    rows = [np.concatenate([pooled[i], pooled[i - 1] if i > 0 else zero, [1.0 if i > 0 else 0.0],
                            pooled[i + 1] if i < n - 1 else zero, [1.0 if i < n - 1 else 0.0], P[i]])
            for i in range(n)]
    return np.asarray(rows, dtype=np.float32).reshape(n, N_FEATURES)


def dtw_distance(a: np.ndarray, b: np.ndarray, band: int) -> float:
    """Mean absolute difference along the cheapest warping path inside a Sakoe–Chiba band."""
    n, m = len(a), len(b)
    cost = np.full((n + 1, m + 1), np.inf)
    steps = np.zeros((n + 1, m + 1))
    cost[0, 0] = 0.0
    for i in range(1, n + 1):
        for j in range(max(1, i - band), min(m, i + band) + 1):
            prev = min(((i - 1, j - 1), (i - 1, j), (i, j - 1)), key=lambda p: cost[p])
            cost[i, j] = cost[prev] + abs(float(a[i - 1]) - float(b[j - 1]))
            steps[i, j] = steps[prev] + 1
    return float(cost[n, m] / steps[n, m])
