"""Pitch, silence trim and speaker baselines (Phase 2 spec §1 steps 1, 4, 5 and §2)."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

STEP_S = 0.01
MIN_SPREAD_ST = 1.0          # a monotone take must not blow normalised values up


@dataclass
class Pitch:
    t0: float                # time of frame 0 (s) on the audio's own axis
    f0: np.ndarray           # Hz per 10 ms frame, nan where unvoiced

    def times(self) -> np.ndarray:
        return self.t0 + STEP_S * np.arange(len(self.f0))

    def voiced(self) -> np.ndarray:
        return self.f0[~np.isnan(self.f0)]


def track_pitch(wav: np.ndarray, sr: int, floor: float = 60, ceiling: float = 500) -> Pitch:
    """parselmouth autocorrelation pitch at 10 ms; one retry at 40–600 Hz when under half the frames are voiced,
    kept only if it finds more voiced frames."""
    import parselmouth
    snd = parselmouth.Sound(np.asarray(wav, dtype=np.float64), sampling_frequency=sr)
    p = _ac(snd, floor, ceiling)
    if len(p.f0) and np.mean(~np.isnan(p.f0)) < 0.5:
        q = _ac(snd, 40, 600)
        if np.sum(~np.isnan(q.f0)) > np.sum(~np.isnan(p.f0)):
            p = q
    return p


def _ac(snd, floor: float, ceiling: float) -> Pitch:
    pitch = snd.to_pitch_ac(time_step=STEP_S, pitch_floor=floor, pitch_ceiling=ceiling)
    f0 = np.asarray(pitch.selected_array["frequency"], dtype=float)
    f0[f0 <= 0] = np.nan
    xs = pitch.xs()
    return Pitch(float(xs[0]) if len(xs) else 0.0, f0)


def trim_silence(wav: np.ndarray, sr: int, keep_s: float = 0.05, rel_db: float = -35.0) -> tuple[np.ndarray, float]:
    """Cut leading and trailing 20 ms frames quieter than `rel_db` below the loudest one, keeping `keep_s` of margin
    (the Flow slice slack, main spec §6.1). Returns the samples and the offset (s) of their first one."""
    hop = int(0.02 * sr)
    n = len(wav) // hop
    if n == 0:
        return wav, 0.0
    rms = np.sqrt(np.mean(wav[: n * hop].astype(np.float64).reshape(n, hop) ** 2, axis=1)) + 1e-12
    loud = np.flatnonzero(20 * np.log10(rms / rms.max()) > rel_db)
    a = max(0, int(loud[0] * hop - keep_s * sr))
    b = min(len(wav), int((loud[-1] + 1) * hop + keep_s * sr))
    return wav[a:b], a / sr


@dataclass
class Baseline:
    hz: float                # median voiced F0
    spread_st: float         # interquartile range in semitones around it


def baseline_of(f0: np.ndarray) -> Baseline | None:
    v = f0[np.isfinite(f0) & (f0 > 0)]
    if len(v) == 0:
        return None
    hz = float(np.median(v))
    q1, q3 = np.percentile(12 * np.log2(v / hz), [25, 75])
    return Baseline(hz, max(float(q3 - q1), MIN_SPREAD_ST))


def blend(profile: Baseline | None, take: Baseline | None, w_take: float) -> Baseline | None:
    """`w_take` of the take's own baseline, the rest from the profile (geometric for Hz), spec §2."""
    if profile is None or (w_take >= 1 and take is not None):
        return take if take is not None else profile
    if take is None or w_take <= 0:
        return profile
    hz = float(np.exp(w_take * np.log(take.hz) + (1 - w_take) * np.log(profile.hz)))
    return Baseline(hz, w_take * take.spread_st + (1 - w_take) * profile.spread_st)


def normalise(f0: np.ndarray, base: Baseline, span: bool) -> np.ndarray:
    """Semitones relative to the baseline (nan stays nan), in units of the speaker's spread when `span`."""
    st = 12 * np.log2(f0 / base.hz)
    return st / base.spread_st if span else st
