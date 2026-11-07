"""The reference clip's pooled embeddings are cached on disk per clip version and embedder (they are the same for
every take of a segment), and a cached value is exactly what scoring would have computed."""
from __future__ import annotations
import os
import threading
from types import SimpleNamespace
import numpy as np
from shadow.scoring.embed import FakeEmbedder, pool
from shadow.scoring.reference import reference_embeddings
from shadow.store.files import FileLayout
from tests.helpers import voice

SR = 16000
WIN = [(0.0, 0.25), (0.25, 0.5), (0.5, 0.75)]


class CountingEmbedder(FakeEmbedder):
    def __init__(self, name="m", revision="r1", layer=8, device="cpu"):
        self.name, self.revision, self.layer, self.device = name, revision, layer, device
        self.calls = 0

    def frames(self, wav, sr):
        self.calls += 1
        return super().frames(wav, sr)


def _setup(tmp_path):
    wav = voice([(220, 220), (150, 300), (300, 150)])
    clip = tmp_path / "clip.wav"
    clip.write_bytes(b"x")                              # only its mtime matters here
    return FileLayout(tmp_path / "data"), SimpleNamespace(id=7, clip_wav_path=str(clip)), wav, clip


def test_a_cached_reference_is_exactly_what_scoring_computes(tmp_path):
    files, seg, wav, _ = _setup(tmp_path)
    emb = CountingEmbedder()
    want = pool(FakeEmbedder().frames(wav, SR), WIN)
    first = reference_embeddings(files, emb, seg, wav, SR, WIN)
    second = reference_embeddings(files, emb, seg, wav, SR, WIN)
    assert emb.calls == 1
    assert first.dtype == second.dtype == want.dtype and np.array_equal(first, want) and np.array_equal(second, want)
    assert len(list(files.cache_dir("emb").iterdir())) == 1


def test_a_recut_clip_is_embedded_again(tmp_path):
    files, seg, wav, clip = _setup(tmp_path)
    emb = CountingEmbedder()
    reference_embeddings(files, emb, seg, wav, SR, WIN)
    st = clip.stat()
    os.utime(clip, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000))
    reference_embeddings(files, emb, seg, wav, SR, WIN)
    assert emb.calls == 2


def test_another_model_revision_layer_or_device_is_embedded_again(tmp_path):
    files, seg, wav, _ = _setup(tmp_path)
    variants = [CountingEmbedder(), CountingEmbedder(name="other"), CountingEmbedder(revision="r2"),
                CountingEmbedder(layer=9), CountingEmbedder(device="cuda")]
    for e in variants:
        reference_embeddings(files, e, seg, wav, SR, WIN)
    assert [e.calls for e in variants] == [1] * 5


def test_other_windows_or_samples_are_embedded_again(tmp_path):
    files, seg, wav, _ = _setup(tmp_path)
    emb = CountingEmbedder()
    reference_embeddings(files, emb, seg, wav, SR, WIN)
    moved = [(0.0, 0.3), (0.3, 0.5), (0.5, 0.75)]
    got = reference_embeddings(files, emb, seg, wav, SR, moved)
    assert emb.calls == 2 and np.array_equal(got, pool(FakeEmbedder().frames(wav, SR), moved))
    louder = wav * 2
    got = reference_embeddings(files, emb, seg, louder, SR, WIN)
    assert emb.calls == 3 and np.array_equal(got, pool(FakeEmbedder().frames(louder, SR), WIN))


def test_a_damaged_cache_file_is_recomputed(tmp_path):
    files, seg, wav, _ = _setup(tmp_path)
    emb = CountingEmbedder()
    reference_embeddings(files, emb, seg, wav, SR, WIN)
    (cached,) = files.cache_dir("emb").iterdir()
    cached.write_bytes(b"not an array")
    got = reference_embeddings(files, emb, seg, wav, SR, WIN)
    assert emb.calls == 2 and np.array_equal(got, pool(FakeEmbedder().frames(wav, SR), WIN))
    assert np.array_equal(np.load(cached), got)                           # and rewritten


def test_concurrent_takes_of_a_segment_all_get_the_right_reference(tmp_path):
    files, seg, wav, _ = _setup(tmp_path)
    want = pool(FakeEmbedder().frames(wav, SR), WIN)
    got, errors = [], []

    def run():
        try:
            got.append(reference_embeddings(files, CountingEmbedder(), seg, wav, SR, WIN))
        except Exception as e:  # noqa: BLE001
            errors.append(e)
    ts = [threading.Thread(target=run) for _ in range(8)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert errors == [] and len(got) == 8 and all(np.array_equal(g, want) for g in got)
    assert [p.name for p in files.cache_dir("emb").iterdir() if not p.name.endswith(".npy")] == []   # no temp left
