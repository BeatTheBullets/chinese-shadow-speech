"""Fuses the two wrong-sound model scores into one ok/slip verdict (spec §3)."""
from __future__ import annotations

from shadow.config import SoundsCfg


def decide(bad_a: float | None, bad_b: float | None, cfg: SoundsCfg) -> tuple[str, float, str] | None:
    """Return (status, z, rule) for a syllable, or None when model B has no reading.

    Both scores present: each is z-normalised on normal takes and summed, so a single noisy model cannot
    flag alone unless it is far out. Only model B: the raw score is compared to its own threshold because
    there is no model-A z-score to combine with. Only model A, or neither: no verdict."""
    if bad_b is None:
        return None
    if bad_a is None:
        z = (bad_b - cfg.z_b_mean) / cfg.z_b_sd
        return ("slip" if bad_b > cfg.b_only_threshold else "ok"), z, "b_only"
    z = (bad_a - cfg.z_a_mean) / cfg.z_a_sd + (bad_b - cfg.z_b_mean) / cfg.z_b_sd
    return ("slip" if z > cfg.fused_threshold else "ok"), z, "fused"
