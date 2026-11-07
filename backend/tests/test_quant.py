import numpy as np
import pytest
import torch
from shadow.config import ModelsCfg, Settings
from shadow.quant import Int8Linear, cpu_threads, int8_wanted, quantize_linear


def test_quantize_linear_swaps_linear_layers_and_keeps_outputs_close():
    torch.manual_seed(0)
    m = torch.nn.Sequential(torch.nn.Linear(64, 64), torch.nn.ReLU(), torch.nn.Linear(64, 8))
    x = torch.randn(4, 64)
    ref = m(x)
    q = quantize_linear(m)
    assert type(q[0]) is Int8Linear and type(q[2]) is Int8Linear
    assert torch.allclose(q(x), ref, atol=0.02)


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
    n_q = sum(isinstance(m, Int8Linear) for m in a._model.modules())
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
    import warnings
    warnings.simplefilter("always")
    q = quantize_linear(torch.nn.Sequential(torch.nn.Linear(8, 8)))
    q(torch.randn(2, 8))
    assert not [w for w in recwarn if issubclass(w.category, DeprecationWarning) or "torch.ao" in str(w.message)]
    assert not [m for m in q.modules() if type(m).__module__.startswith("torch.ao")]


def test_int8_skip_keeps_named_models_fp32(tmp_path, monkeypatch):
    from shadow.deps import build_deps
    monkeypatch.setattr("shadow.quant.total_ram_gb", lambda: 8)       # the recogniser's precision depends on the RAM
    cfg = ModelsCfg(device="cpu", int8=True, int8_skip=["asr", "sounds"])
    deps = build_deps(Settings(models=cfg, data_dir=tmp_path))
    assert deps.asr.int8 is False
    assert deps.aligner.inner.int8 is True
    assert deps.sounds.chars.int8 is False
    on = build_deps(Settings(models=ModelsCfg(device="cpu", int8=True), data_dir=tmp_path))
    assert (on.asr.int8, on.aligner.inner.int8, on.sounds.chars.int8) == (True, True, True)


@pytest.mark.parametrize("ram,device,int8,skip,expected", [
    (8, "cpu", True, [], True), (16, "cpu", True, [], False), (11.9, "cpu", True, [], True), (12, "cpu", True, [], False),
    (8, "cpu", False, [], False), (8, "cuda", True, [], False), (8, "cpu", True, ["asr"], False)])
def test_recogniser_int8_depends_on_ram(monkeypatch, ram, device, int8, skip, expected):
    import shadow.quant as q
    monkeypatch.setattr(q, "total_ram_gb", lambda: ram)
    assert q.asr_int8(Settings(models=ModelsCfg(device=device, int8=int8, int8_skip=skip))) is expected


def test_quantize_linear_keeps_a_weight_tied_to_an_embedding():
    # e.g. a language-model head tied to the input embedding: emptying the Linear's fp32 weight would empty the
    # Embedding's too, since both hold the same Parameter
    torch.manual_seed(0)
    emb = torch.nn.Embedding(10, 8)
    head = torch.nn.Linear(8, 10, bias=False)
    head.weight = emb.weight
    model = torch.nn.Sequential(emb, head)
    ids = torch.tensor([[1, 2, 3]])
    with torch.no_grad():
        want_emb = emb(ids).clone()
        want = model(ids).clone()
    quantize_linear(model)
    with torch.no_grad():
        assert torch.equal(model[0](ids), want_emb)
        assert isinstance(model[1], Int8Linear)
        assert torch.allclose(model(ids), want, atol=0.05)


def test_cpu_threads_is_physical_cores_minus_one(monkeypatch):
    import psutil
    monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 4 if not logical else 8)
    assert cpu_threads(Settings(models=ModelsCfg(threads=0))) == 3


def test_cpu_threads_without_a_physical_count_halves_the_logical_cores(monkeypatch):
    """psutil may not know the physical cores: 8 logical are then taken as 4 physical (SMT), so 3 threads, not 7."""
    import os
    import psutil
    monkeypatch.setattr(psutil, "cpu_count", lambda logical=True: 8 if logical else None)
    monkeypatch.setattr(os, "cpu_count", lambda: 8)
    assert cpu_threads(Settings(models=ModelsCfg(threads=0))) == 3
