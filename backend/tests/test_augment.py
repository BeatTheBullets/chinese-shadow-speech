import numpy as np
import pytest
from shadow.scoring.augment import alter_choices, contour_units, resynth
from shadow.scoring.pitch import Baseline, track_pitch
from tests.helpers import voice

SR = 16000


def test_contour_units_shapes():
    rng = np.random.default_rng(0)
    assert np.all(contour_units("flat", rng) == 0)
    rise = contour_units(2, rng); fall = contour_units(4, rng)
    assert rise[-1] > rise[0] and fall[-1] < fall[0]
    assert np.ptp(contour_units(1, rng)) == pytest.approx(0.0)


def test_alter_choices_never_keeps_the_own_tone():
    rng = np.random.default_rng(1)
    for _ in range(50):
        ch, lab = alter_choices([1, 2, 3, 4, 0, None], rng)
        assert all(c != t for c, t in zip(ch[:4], [1, 2, 3, 4]))
        assert lab[4] == -1 and lab[5] == -1
        assert all(l == (1 if c == "flat" else c) for c, l in zip(ch[:4], lab[:4]))


def test_resynth_imposes_a_rise_on_a_flat_voice():
    wav = voice([(180, 180)], syl_s=0.6)
    base = Baseline(180.0, 4.0)
    out = resynth(wav, SR, [(0.0, 0.6)], [np.array([-1.0, -0.5, 0.0, 0.5, 1.0])], base, 60, 500)
    f0 = track_pitch(out, SR).voiced()
    assert len(out) == pytest.approx(len(wav), abs=SR // 100)
    assert f0[-5:].mean() > f0[:5].mean() * 1.2
    assert np.array_equal(resynth(wav, SR, [(0.0, 0.6)], None, base, 60, 500), wav)
