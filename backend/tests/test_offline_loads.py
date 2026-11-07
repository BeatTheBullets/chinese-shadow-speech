"""Models already on disk load without the network: every loader resolves the local copy first and downloads only
when the files are missing (first run, prepare). Fake models, no downloads."""
import sys
import types

import pytest

import shadow.hf as hf

PARAFORMER = "iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
VAD = "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"


class _CacheNotFound(Exception):
    """modelscope_hub's CacheNotFound is a plain Exception, not an OSError."""


def _fake_snapshots(monkeypatch, tmp_path, cached: set[str], no_weights: frozenset[str] = frozenset()):
    """A ModelScope cache holding snapshots of `cached`, complete except those in `no_weights` (an interrupted first
    download: the directory is there, model.pt is not). Records every lookup."""
    lookups = []

    def snapshot_download(model_id, revision=None, local_files_only=False, **kw):
        lookups.append((model_id, revision, local_files_only))
        if not local_files_only:
            pytest.fail("the loader must leave downloads to FunASR")
        if model_id not in cached:
            raise _CacheNotFound(f"no snapshot of {model_id}")
        d = tmp_path / model_id.replace("/", "--") / "snapshots" / (revision or "master")
        d.mkdir(parents=True, exist_ok=True)
        for f in ("configuration.json", "config.yaml") + (() if model_id in no_weights else ("model.pt",)):
            (d / f).write_text("x")
        return str(d)
    monkeypatch.setitem(sys.modules, "modelscope.hub.snapshot_download",
                        types.SimpleNamespace(snapshot_download=snapshot_download))
    return lookups


def _fake_automodel(monkeypatch):
    seen = {}

    class FakeAutoModel:
        def __init__(self, **kw):
            seen.update(kw)
    monkeypatch.setitem(sys.modules, "funasr", types.SimpleNamespace(AutoModel=FakeAutoModel))
    return seen


def test_the_recogniser_loads_the_cached_snapshots_by_their_directories(monkeypatch, tmp_path):
    from shadow.ingest.asr import ParaformerASR
    lookups = _fake_snapshots(monkeypatch, tmp_path, {PARAFORMER, VAD})
    seen = _fake_automodel(monkeypatch)
    ParaformerASR(PARAFORMER, "cpu")._load()
    assert seen["model"] == str(tmp_path / PARAFORMER.replace("/", "--") / "snapshots" / "master")
    assert seen["vad_model"] == str(tmp_path / VAD.replace("/", "--") / "snapshots" / "master")
    assert seen["disable_update"] is True
    assert sorted(lookups) == sorted([(PARAFORMER, "master", True), (VAD, "master", True)])


def test_the_recogniser_passes_model_ids_when_nothing_is_cached(monkeypatch, tmp_path):
    from shadow.ingest.asr import ParaformerASR
    _fake_snapshots(monkeypatch, tmp_path, set())
    seen = _fake_automodel(monkeypatch)
    ParaformerASR(PARAFORMER, "cpu")._load()
    assert seen["model"] == PARAFORMER and seen["vad_model"] == "fsmn-vad"


def test_a_partly_downloaded_snapshot_is_left_to_funasr_to_finish(monkeypatch, tmp_path):
    from shadow.ingest.asr import ParaformerASR
    _fake_snapshots(monkeypatch, tmp_path, {PARAFORMER, VAD}, no_weights=frozenset({VAD}))
    seen = _fake_automodel(monkeypatch)
    ParaformerASR(PARAFORMER, "cpu")._load()
    assert seen["vad_model"] == "fsmn-vad"
    assert seen["model"] != PARAFORMER


class _Pretrained:
    """A fake transformers class: cached (or not) on disk; records every from_pretrained call's kwargs."""
    cached = True

    def __init_subclass__(cls):
        cls.calls = []

    @classmethod
    def from_pretrained(cls, name, **kw):
        cls.calls.append(kw)
        if kw.get("local_files_only") and not cls.cached:
            raise OSError(f"{name} is not in the cache")
        return cls()

    def to(self, device): return self
    def eval(self): return self


class _Model(_Pretrained):
    config = types.SimpleNamespace(vocab_size=4, pad_token_id=0)


class _CtcModel(_Model):
    pass


class _Tokenizer(_Pretrained):
    def get_vocab(self): return {}


def test_the_tone_model_loads_its_cached_copy_without_the_network(monkeypatch):
    from shadow.scoring.embed import Wav2Vec2Embedder

    class M(_Model): pass
    monkeypatch.setattr(hf, "_classes", (M, None, None))
    Wav2Vec2Embedder("n", "rev", 9, "cpu")._load()
    assert M.calls == [{"revision": "rev", "local_files_only": True}]


def test_the_tone_model_downloads_when_not_cached(monkeypatch):
    from shadow.scoring.embed import Wav2Vec2Embedder

    class M(_Model): cached = False
    monkeypatch.setattr(hf, "_classes", (M, None, None))
    Wav2Vec2Embedder("n", "rev", 9, "cpu")._load()
    assert M.calls == [{"revision": "rev", "local_files_only": True}, {"revision": "rev"}]


def test_the_sounds_model_and_its_tokenizer_load_their_cached_copies_without_the_network(monkeypatch):
    from shadow.scoring.sounds.charctc import CharCtc

    class C(_CtcModel): pass

    class T(_Tokenizer): pass
    monkeypatch.setattr(hf, "_classes", (None, C, T))
    CharCtc("n", "rev", "cpu")._load()
    assert C.calls == [{"revision": "rev", "low_cpu_mem_usage": True, "local_files_only": True}]
    assert T.calls == [{"revision": "rev", "local_files_only": True}]


def test_the_sounds_model_downloads_when_not_cached(monkeypatch):
    from shadow.scoring.sounds.charctc import CharCtc

    class C(_CtcModel): cached = False

    class T(_Tokenizer): cached = False
    monkeypatch.setattr(hf, "_classes", (None, C, T))
    CharCtc("n", "rev", "cpu")._load()
    assert C.calls[-1] == {"revision": "rev", "low_cpu_mem_usage": True}
    assert T.calls == [{"revision": "rev", "local_files_only": True}, {"revision": "rev"}]
