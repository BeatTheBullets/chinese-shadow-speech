from __future__ import annotations

import pytest

from shadow.config import SoundsCfg
from shadow.scoring.sounds.decide import decide


@pytest.fixture
def cfg() -> SoundsCfg:
    return SoundsCfg()


def test_fused_both_scores_ok(cfg: SoundsCfg):
    status, z, rule = decide(0.28, 6.78, cfg)
    assert status == "ok" and rule == "fused"
    assert z == pytest.approx((0.28 + 4.006537) / 2.974512 + (6.78 - 1.239741) / 3.072057, abs=1e-6)


def test_fused_both_scores_slip(cfg: SoundsCfg):
    status, z, rule = decide(10.0, 20.0, cfg)
    assert (status, rule) == ("slip", "fused")
    assert z > cfg.fused_threshold


def test_b_only_slip(cfg: SoundsCfg):
    status, z, rule = decide(None, 28.0, cfg)
    assert (status, rule) == ("slip", "b_only")
    assert z == pytest.approx((28.0 - cfg.z_b_mean) / cfg.z_b_sd)


def test_b_only_ok(cfg: SoundsCfg):
    status, _, rule = decide(None, 1.5, cfg)
    assert (status, rule) == ("ok", "b_only")


def test_a_only_or_neither_is_none(cfg: SoundsCfg):
    assert decide(3.0, None, cfg) is None
    assert decide(None, None, cfg) is None
