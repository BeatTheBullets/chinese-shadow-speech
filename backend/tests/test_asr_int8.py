"""The 8-bit recogniser is stored like the aligner's int8 copy: after the first load, a start builds FunASR's AutoModel
without reading the fp32 checkpoint and swaps in the stored int8 module. Fakes stand in for FunASR (no real model)."""
import os
import sys
import types
import pytest

torch = pytest.importorskip("torch")

from shadow.quant import Int8Linear


def _net():
    torch.manual_seed(0)
    return torch.nn.Sequential(torch.nn.Linear(8, 16), torch.nn.ReLU(), torch.nn.Linear(16, 4))


@pytest.fixture
def fake_funasr(monkeypatch, tmp_path):
    """A FunASR whose AutoModel builds a small net for the recogniser and the VAD, each read through
    funasr.auto.auto_model.load_pretrained_model(path=<dir>/model.pt, model=...), as FunASR's build_model does."""
    monkeypatch.setenv("SHADOW_MODELS_DIR", str(tmp_path / "models"))
    main, vad = tmp_path / "paraformer", tmp_path / "vad"
    main.mkdir(), vad.mkdir()
    loads, builds = [], []
    am = types.ModuleType("funasr.auto.auto_model")

    def load_pretrained_model(path, model, **kw):
        loads.append(os.path.dirname(path))
        with torch.no_grad():
            for p in model.parameters():
                p.fill_(0.5)

    am.load_pretrained_model = load_pretrained_model

    class FakeAutoModel:
        def __init__(self, **kw):
            builds.append(kw)
            self.model, self.vad_model = _net(), _net()
            am.load_pretrained_model(path=os.path.join(kw["model"], "model.pt"), model=self.model)
            am.load_pretrained_model(path=os.path.join(kw["vad_model"], "model.pt"), model=self.vad_model)

    funasr = types.ModuleType("funasr")
    funasr.AutoModel, funasr.__version__ = FakeAutoModel, "9.9.9"
    monkeypatch.setitem(sys.modules, "funasr", funasr)
    monkeypatch.setitem(sys.modules, "funasr.auto", types.ModuleType("funasr.auto"))
    monkeypatch.setitem(sys.modules, "funasr.auto.auto_model", am)
    snapshots = {"m": str(main), "fsmn-vad": str(vad)}
    monkeypatch.setattr("shadow.ingest.asr._local_snapshot", lambda name: snapshots[name])
    return types.SimpleNamespace(main=str(main), vad=str(vad), loads=loads, builds=builds, am=am,
                                 real_load=load_pretrained_model)


def _load(int8=True):
    from shadow.ingest.asr import ParaformerASR
    return ParaformerASR("m", "cpu", int8=int8)._load()


def test_the_first_int8_load_reads_the_checkpoint_quantises_and_stores_the_module(fake_funasr, tmp_path):
    model = _load()
    assert fake_funasr.loads == [fake_funasr.main, fake_funasr.vad]
    assert type(model.model[0]) is Int8Linear
    stored = list((tmp_path / "models" / "int8").glob("m-funasr9.9.9-q*-torch*.pt"))
    assert len(stored) == 1


def test_a_later_int8_load_skips_the_recognisers_checkpoint_and_uses_the_stored_module(fake_funasr):
    first = _load()
    fake_funasr.loads.clear()
    second = _load()
    assert fake_funasr.loads == [fake_funasr.vad]                # the VAD still loads its own weights
    assert type(second.model[0]) is Int8Linear
    x = torch.randn(3, 8)
    assert torch.equal(first.model(x), second.model(x))           # the same int8 weights: the same outputs
    assert fake_funasr.am.load_pretrained_model is fake_funasr.real_load      # FunASR's loader is put back


def test_an_unreadable_stored_module_is_rebuilt_from_the_checkpoint(fake_funasr, tmp_path):
    _load()
    [stored] = (tmp_path / "models" / "int8").glob("*.pt")
    stored.write_bytes(b"not a model")
    fake_funasr.loads.clear()
    model = _load()
    assert fake_funasr.main in fake_funasr.loads
    assert type(model.model[0]) is Int8Linear


def test_without_funasrs_loader_a_stored_load_still_swaps_in_the_int8_module(fake_funasr, monkeypatch):
    """A FunASR whose builder looks different (its module cannot be imported): the checkpoint is read as before,
    and the stored int8 module still replaces it."""
    first = _load()
    monkeypatch.setitem(sys.modules, "funasr.auto.auto_model", None)          # importing it fails
    fake_funasr.loads.clear()
    second = _load()
    assert fake_funasr.loads == [fake_funasr.main, fake_funasr.vad]
    assert type(second.model[0]) is Int8Linear
    x = torch.randn(3, 8)
    assert torch.equal(first.model(x), second.model(x))


def test_the_fp32_recogniser_is_never_stored(fake_funasr, tmp_path):
    model = _load(int8=False)
    assert type(model.model[0]) is torch.nn.Linear
    assert not (tmp_path / "models" / "int8").exists()
    assert fake_funasr.loads == [fake_funasr.main, fake_funasr.vad]
