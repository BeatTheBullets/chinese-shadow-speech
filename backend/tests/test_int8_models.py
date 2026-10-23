"""Real-model checks for the low-memory loading paths (need the downloaded models; run with -m models)."""
import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytestmark = pytest.mark.models


def wav():
    t = np.arange(16000 * 2) / 16000
    return (0.3 * np.sin(2 * np.pi * 180 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t))).astype(np.float32)


def test_mms_model_equals_get_model_and_has_no_meta_tensors():
    import torchaudio
    from shadow.ingest.align import _mms_model
    bundle = torchaudio.pipelines.MMS_FA
    ref, got = bundle.get_model(with_star=False).eval(), _mms_model(bundle)
    assert not any(t.is_meta for t in [*got.parameters(), *got.buffers()])
    x = torch.from_numpy(wav()).unsqueeze(0)
    with torch.inference_mode():
        assert torch.equal(ref(x)[0], got(x)[0])


def test_mms_int8_cold_and_warm_load_give_equal_outputs(tmp_path, monkeypatch):
    from shadow.ingest.align import MmsAligner
    monkeypatch.setenv("SHADOW_MODELS_DIR", str(tmp_path))
    torch.set_num_threads(2)
    cold = MmsAligner("cpu", int8=True).emissions(wav(), 16000)[0]
    assert list((tmp_path / "int8").glob("mms_fa-*.pt"))
    warm = MmsAligner("cpu", int8=True).emissions(wav(), 16000)[0]
    assert torch.equal(cold, warm)


def test_charctc_int8_cold_and_warm_load_give_equal_outputs(tmp_path, monkeypatch):
    from shadow.config import SoundsCfg
    from shadow.scoring.sounds.charctc import CharCtc
    monkeypatch.setenv("SHADOW_MODELS_DIR", str(tmp_path))
    torch.set_num_threads(2)
    cfg = SoundsCfg()
    cold = CharCtc(cfg.model, cfg.revision, "cpu", True).group_logp(wav(), 16000)
    assert list((tmp_path / "int8").glob("*.pt"))
    warm = CharCtc(cfg.model, cfg.revision, "cpu", True).group_logp(wav(), 16000)
    assert torch.equal(cold, warm)
