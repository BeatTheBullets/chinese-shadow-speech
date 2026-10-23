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
    assert pool(frames, [(0.041, 0.042)])[0, 0] == 1.0      # midpoint 0.0415: frame 1 (centre 0.0325) is nearer than frame 2 (0.0525)
    assert FRAME_S == 0.02


def _warm_client(data_dir, embedder):
    from fastapi.testclient import TestClient
    from shadow.config import Settings
    from shadow.deps import fake_deps
    from shadow.ingest.transcript import Transcript
    from shadow.main import create_app
    s = Settings(data_dir=data_dir)
    s.models.device = "cuda"                     # the embedder warms at startup only off the CPU; fake deps run anywhere
    deps = fake_deps(s, Transcript()); deps.embedder = embedder
    return TestClient(create_app(s, deps=deps))


def test_the_speech_model_warms_up_at_start_up(data_dir, monkeypatch):
    """The first-ever scored take would otherwise wait for a ~380 MB download (spec §10): start it with the app,
    in the background, under the embedder's lock (a take arriving meanwhile waits for the same load)."""
    import threading
    from shadow.scoring.embed import Wav2Vec2Embedder
    emb = Wav2Vec2Embedder("none", "none", 0, "cpu")
    loaded = threading.Event()

    def load(self):
        assert self._lock.locked(); loaded.set()
    monkeypatch.setattr(Wav2Vec2Embedder, "_load", load)
    with _warm_client(data_dir, emb):
        assert loaded.wait(5)


def test_a_failed_warm_up_is_logged_not_raised(data_dir, monkeypatch, caplog):
    import threading
    from shadow.scoring.embed import Wav2Vec2Embedder
    tried = threading.Event()

    def load(self):
        tried.set(); raise OSError("offline")
    monkeypatch.setattr(Wav2Vec2Embedder, "_load", load)
    with _warm_client(data_dir, Wav2Vec2Embedder("none", "none", 0, "cpu")) as c:
        assert tried.wait(5)
        assert c.get("/health").status_code == 200
    for _ in range(50):                          # the thread logs just after _load raises
        if "warming up" in caplog.text:
            break
        threading.Event().wait(0.02)
    assert "warming up" in caplog.text and "offline" in caplog.text


def test_fake_deps_do_not_warm_up(data_dir, monkeypatch):
    from shadow.scoring.embed import Wav2Vec2Embedder
    monkeypatch.setattr(Wav2Vec2Embedder, "_load", lambda self: pytest.fail("no model in tests"))
    with _warm_client(data_dir, FakeEmbedder()) as c:
        assert c.get("/health").status_code == 200
