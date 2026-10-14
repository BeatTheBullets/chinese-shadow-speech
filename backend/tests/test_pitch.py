import numpy as np
import pytest
from shadow.scoring.pitch import Baseline, STEP_S, baseline_of, blend, normalise, track_pitch, trim_silence
from tests.helpers import voice

SR = 16000


def test_track_pitch_follows_a_steady_and_a_rising_voice():
    p = track_pitch(voice([(200, 200)], syl_s=1.0), SR)
    assert abs(np.nanmedian(p.f0) - 200) < 2
    assert np.mean(~np.isnan(p.f0)) > 0.8
    rise = track_pitch(voice([(150, 300)], syl_s=1.0), SR)
    v = rise.f0[~np.isnan(rise.f0)]
    assert v[-5:].mean() > v[:5].mean() + 100
    assert abs(rise.times()[1] - rise.times()[0] - STEP_S) < 1e-9


def test_track_pitch_marks_silence_unvoiced():
    p = track_pitch(np.zeros(SR, dtype="float32"), SR)
    assert np.isnan(p.f0).all() and len(p.voiced()) == 0


def test_trim_silence_cuts_both_ends_and_reports_the_offset():
    x = voice([(200, 200)], syl_s=0.5, lead_s=0.6)
    y, off = trim_silence(x, SR)
    assert 0.5 <= off <= 0.6
    assert 0.55 <= len(y) / SR <= 0.65


def test_trim_silence_leaves_silence_alone():
    x = np.zeros(SR // 2, dtype="float32")
    y, off = trim_silence(x, SR)
    assert off == 0.0 and len(y) == len(x)


def test_baseline_is_median_and_semitone_iqr():
    f0 = np.array([100.0, 100.0, 200.0, 200.0, np.nan])
    b = baseline_of(f0)
    assert b.hz == pytest.approx(150.0)
    st = 12 * np.log2(np.array([100, 100, 200, 200]) / 150.0)
    q1, q3 = np.percentile(st, [25, 75])
    assert b.spread_st == pytest.approx(q3 - q1)
    assert baseline_of(np.array([np.nan])) is None


def test_baseline_spread_has_a_floor():
    assert baseline_of(np.full(50, 180.0)).spread_st == 1.0


def test_blend_weights_take_and_profile():
    prof, take = Baseline(100.0, 4.0), Baseline(400.0, 8.0)
    assert blend(None, take, 0.2) == take
    assert blend(prof, None, 0.8) == prof
    assert blend(prof, take, 0.0) == prof
    mid = blend(prof, take, 0.5)
    assert mid.hz == pytest.approx(200.0) and mid.spread_st == pytest.approx(6.0)


def test_normalise_is_semitones_over_spread():
    b = Baseline(100.0, 2.0)
    out = normalise(np.array([200.0, np.nan]), b, span=False)
    assert out[0] == pytest.approx(12.0) and np.isnan(out[1])
    assert normalise(np.array([200.0]), b, span=True)[0] == pytest.approx(6.0)
