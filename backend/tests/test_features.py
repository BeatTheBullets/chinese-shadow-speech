import numpy as np
import pytest
from shadow.scoring.features import (FEATURE_VERSION, N_FEATURES, POINTS, SylPitch, dtw_distance, feature_matrix,
                                     syllable_pitch)


def test_syllable_pitch_trims_and_resamples_voiced_frames():
    norm = np.linspace(-1, 1, 100)                 # 1 s rising line on a 10 ms grid starting at t0 = 0
    s = syllable_pitch(norm, 0.0, 0.0, 1.0, min_voiced=4)
    assert s.contour.shape == (POINTS,) and s.voiced_ratio == 1.0 and s.duration == 1.0
    assert s.contour[0] == pytest.approx(-0.7, abs=0.03) and s.contour[-1] == pytest.approx(0.7, abs=0.03)


def test_syllable_pitch_unvoiced_below_min_frames():
    norm = np.full(100, np.nan); norm[50:53] = 0.0
    s = syllable_pitch(norm, 0.0, 0.0, 1.0, min_voiced=4)
    assert s.contour is None and 0 < s.voiced_ratio < 0.1


def test_syllable_pitch_respects_t0():
    norm = np.concatenate([np.zeros(50), np.ones(50)])
    s = syllable_pitch(norm, 0.5, 0.5, 1.0, min_voiced=4)      # frames 0..49 cover 0.5–1.0 s
    assert np.allclose(s.contour, 0.0)


def test_feature_matrix_shape_and_neighbours():
    up = SylPitch(np.linspace(-1, 1, POINTS), 1.0, 0.2)
    down = SylPitch(np.linspace(1, -1, POINTS), 1.0, 0.2)
    quiet = SylPitch(None, 0.1, 0.1)
    X = feature_matrix([up, down, quiet])
    assert X.shape == (3, N_FEATURES) and X.dtype == np.float32
    assert np.allclose(X[0, :POINTS], up.contour)
    assert not np.allclose(X[0], X[1])
    assert FEATURE_VERSION == 1


def test_feature_matrix_single_syllable_has_empty_neighbours():
    X = feature_matrix([SylPitch(np.zeros(POINTS), 1.0, 0.3)])
    assert X.shape == (1, N_FEATURES) and np.isfinite(X).all()


def test_dtw_distance():
    a = np.sin(np.linspace(0, 3, 20))
    assert dtw_distance(a, a, 4) == 0.0
    assert dtw_distance(a, a + 2.0, 4) == pytest.approx(2.0)
    shifted = np.sin(np.linspace(0.3, 3.3, 20))
    assert dtw_distance(a, shifted, 4) < np.mean(np.abs(a - shifted))
