import numpy as np
import pytest
from shadow.scoring.features import (FEATURE_VERSION, N_FEATURES, N_PITCH, POINTS, SylPitch, dtw_distance,
                                     feature_matrix, pitch_matrix, syllable_pitch)


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


def test_pitch_matrix_shape_and_neighbours():
    up = SylPitch(np.linspace(-1, 1, POINTS), 1.0, 0.2)
    down = SylPitch(np.linspace(1, -1, POINTS), 1.0, 0.2)
    quiet = SylPitch(None, 0.1, 0.1)
    X = pitch_matrix([up, down, quiet])
    assert X.shape == (3, N_PITCH) and X.dtype == np.float32
    assert np.allclose(X[0, :POINTS], up.contour) and not np.allclose(X[0], X[1])


def test_feature_matrix_concatenates_embeddings_context_and_pitch():
    from shadow.scoring.embed import DIM
    sylls = [SylPitch(np.zeros(POINTS), 1.0, 0.2), SylPitch(None, 0.0, 0.1), SylPitch(np.ones(POINTS), 1.0, 0.2)]
    pooled = np.stack([np.full(DIM, i + 1, np.float32) for i in range(3)])
    X = feature_matrix(sylls, pooled)
    assert X.shape == (3, N_FEATURES) and N_FEATURES == 3 * DIM + 2 + N_PITCH and FEATURE_VERSION == 2
    own, prv, pflag = X[1, :DIM], X[1, DIM:2 * DIM], X[1, 2 * DIM]
    nxt, nflag = X[1, 2 * DIM + 1:3 * DIM + 1], X[1, 3 * DIM + 1]
    assert own[0] == 2 and prv[0] == 1 and pflag == 1 and nxt[0] == 3 and nflag == 1
    assert X[0, 2 * DIM] == 0 and np.all(X[0, DIM:2 * DIM] == 0)          # no previous syllable
    assert X[2, 3 * DIM + 1] == 0                                          # no next syllable
    assert np.allclose(X[:, -N_PITCH:], pitch_matrix(sylls))


def test_dtw_distance():
    a = np.sin(np.linspace(0, 3, 20))
    assert dtw_distance(a, a, 4) == 0.0
    assert dtw_distance(a, a + 2.0, 4) == pytest.approx(2.0)
    shifted = np.sin(np.linspace(0.3, 3.3, 20))
    assert dtw_distance(a, shifted, 4) < np.mean(np.abs(a - shifted))
