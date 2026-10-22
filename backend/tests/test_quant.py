import numpy as np
import pytest
import torch
from shadow.config import ModelsCfg, Settings
from shadow.quant import cpu_threads, int8_wanted, quantize_linear


def test_quantize_linear_swaps_linear_layers_and_keeps_outputs_close():
    torch.manual_seed(0)
    m = torch.nn.Sequential(torch.nn.Linear(64, 64), torch.nn.ReLU(), torch.nn.Linear(64, 8))
    x = torch.randn(4, 64)
    ref = m(x)
    q = quantize_linear(m)
    assert isinstance(q[0], torch.ao.nn.quantized.dynamic.Linear)
    assert torch.allclose(q(x), ref, atol=0.05)


def test_int8_only_on_cpu():
    assert int8_wanted(Settings(models=ModelsCfg(device="cuda", int8=True))) is False
    assert int8_wanted(Settings(models=ModelsCfg(device="cpu", int8=True))) is True
    assert int8_wanted(Settings(models=ModelsCfg(device="cpu", int8=False))) is False


def test_cpu_threads_explicit_and_auto():
    assert cpu_threads(Settings(models=ModelsCfg(threads=3))) == 3
    assert cpu_threads(Settings(models=ModelsCfg(threads=0))) >= 1


@pytest.mark.models
def test_mms_aligner_int8_gives_one_span_per_speech_character():
    """No speech WAV is committed, and the aligner returns one span per character for any audio, so a synthetic
    syllable-like signal (an amplitude-modulated tone) with its text exercises the quantised model."""
    from shadow.ingest.align import MmsAligner, speech_chars
    sr = 16000
    t = np.arange(sr * 3) / sr
    wav = (0.3 * np.sin(2 * np.pi * 180 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 3 * t))).astype(np.float32)
    text = "你好,世界。"
    a = MmsAligner("cpu", int8=True)
    spans = a.align(wav, sr, text)
    assert [s.ch for s in spans] == speech_chars(text)
    n_q = sum(isinstance(m, torch.ao.nn.quantized.dynamic.Linear) for m in a._model.modules())
    assert n_q > 0


def test_build_deps_on_cpu_survives_missing_torch(monkeypatch, tmp_path):
    import builtins
    from shadow.deps import build_deps
    real = builtins.__import__

    def no_torch(name, *a, **k):
        if name == "torch" or name.startswith("torch."):
            raise ImportError("no torch")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", no_torch)
    deps = build_deps(Settings(models=ModelsCfg(device="cpu", int8=True), data_dir=tmp_path))
    assert deps.asr is not None


def test_quantize_linear_prints_no_deprecation_warning(recwarn):
    quantize_linear(torch.nn.Sequential(torch.nn.Linear(8, 8)))
    assert not [w for w in recwarn if "torch.ao.quantization" in str(w.message)]


def test_int8_skip_keeps_named_models_fp32(tmp_path):
    from shadow.deps import build_deps
    cfg = ModelsCfg(device="cpu", int8=True, int8_skip=["asr", "sounds"])
    deps = build_deps(Settings(models=cfg, data_dir=tmp_path))
    assert deps.asr.int8 is False
    assert deps.aligner.inner.int8 is True
    assert deps.sounds.chars.int8 is False
    on = build_deps(Settings(models=ModelsCfg(device="cpu", int8=True), data_dir=tmp_path))
    assert (on.asr.int8, on.aligner.inner.int8, on.sounds.chars.int8) == (True, True, True)
