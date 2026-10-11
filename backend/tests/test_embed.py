import numpy as np
import pytest
from shadow.scoring.embed import DIM, FRAME_S, FakeEmbedder, pool


def test_fake_embedder_shape_and_determinism():
    wav = np.linspace(-0.5, 0.5, 16000, dtype=np.float32)
    a, b = FakeEmbedder().frames(wav, 16000), FakeEmbedder().frames(wav, 16000)
    assert a.shape == (50, DIM) and a.dtype == np.float32 and np.array_equal(a, b)


def test_pool_means_frames_whose_centres_fall_in_the_span():
    frames = np.repeat(np.arange(10, dtype=np.float32)[:, None], DIM, axis=1)   # frame i holds value i
    out = pool(frames, [(0.0, 0.05), (0.06, 0.1), (0.5, 0.6)])
    # centres: 0.0125, 0.0325, 0.0525 … → span 1 takes frames 0,1; span 2 takes frames 3,4
    assert out.shape == (3, DIM)
    assert out[0, 0] == pytest.approx(0.5) and out[1, 0] == pytest.approx(3.5)
    assert out[2, 0] == 9.0                                                     # beyond the end: nearest frame


def test_pool_empty_span_takes_nearest_frame():
    frames = np.repeat(np.arange(10, dtype=np.float32)[:, None], DIM, axis=1)
    assert pool(frames, [(0.041, 0.042)])[0, 0] == 2.0
    assert FRAME_S == 0.02
