"""Metrics for comparing forced aligners on a real lesson (addendum spec §1.1); used by scripts/compare_aligners.py."""
from __future__ import annotations
import statistics
from dataclasses import dataclass
import numpy as np
from shadow.ingest.align import Span

FRAME_S = 0.02


def energy_onset(wav: np.ndarray, sr: int, start: float, end: float, rel: float = 0.15) -> float | None:
    """Start of the first 20 ms frame in [start, end) whose RMS reaches `rel` × the loudest frame there; None for a
    window shorter than one frame or a silent one."""
    n = int(FRAME_S * sr)
    a, b = max(0, int(start * sr)), min(len(wav), int(end * sr))
    if b - a < n:
        return None
    frames = wav[a:a + (b - a) // n * n].reshape(-1, n).astype("float64")
    rms = np.sqrt((frames ** 2).mean(axis=1))
    if rms.max() <= 0:
        return None
    k = int(np.argmax(rms >= rel * rms.max()))
    return round((a + k * n) / sr, 3)


def zero_length_share(sentences: list[list[Span]]) -> float:
    """Share of spans shorter than 1 ms across all sentences (0.0 when there are none)."""
    spans = [s for sent in sentences for s in sent]
    return sum(1 for s in spans if s.end - s.start < 0.001) / len(spans) if spans else 0.0


@dataclass
class OnsetError:
    n: int
    mean_ms: float
    median_ms: float
    within_100ms: float          # share of sentences whose onset is within 100 ms of the energy onset


def onset_error(predicted: list[float | None], truth: list[float | None]) -> OnsetError:
    """First-character onset error against the energy onset, over the sentences where both exist."""
    errs = [abs(p - t) * 1000 for p, t in zip(predicted, truth) if p is not None and t is not None]
    if not errs:
        return OnsetError(0, float("nan"), float("nan"), 0.0)
    return OnsetError(len(errs), round(statistics.fmean(errs), 1), round(statistics.median(errs), 1),
                      round(sum(1 for e in errs if e <= 100) / len(errs), 3))


def verdict(qwen: OnsetError, qwen_zero: float, mms: OnsetError, mms_zero: float) -> str:
    """"mms_fa" when MMS_FA is clearly better than the repaired Qwen3 spans (mean onset error at least 30 % lower and
    no more zero-length spans), else "qwen3_fa"."""
    if mms.n and qwen.n and mms.mean_ms <= 0.7 * qwen.mean_ms and mms_zero <= qwen_zero:
        return "mms_fa"
    return "qwen3_fa"
