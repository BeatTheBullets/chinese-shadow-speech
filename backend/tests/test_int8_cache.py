import pytest

torch = pytest.importorskip("torch")

from shadow.quant import cached_int8, quantize_linear


def tiny():
    torch.manual_seed(0)
    return torch.nn.Sequential(torch.nn.Linear(16, 32), torch.nn.GELU(), torch.nn.Linear(32, 4))


def test_quantize_linear_matches_dynamic_quantisation():
    x = torch.randn(3, 16)
    ref = torch.ao.quantization.quantize_dynamic(tiny().eval(), {torch.nn.Linear}, dtype=torch.qint8)(x)
    got = quantize_linear(tiny())(x)
    assert torch.allclose(ref, got, atol=1e-6)


def test_cached_int8_second_load_gives_identical_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("SHADOW_MODELS_DIR", str(tmp_path))
    x = torch.randn(3, 16)
    calls = []

    def build():
        calls.append(1)
        return quantize_linear(tiny())

    first = cached_int8("tiny", build)(x)
    second = cached_int8("tiny", build)(x)
    assert len(calls) == 1 and torch.equal(first, second)


def test_cache_key_changes_with_library_versions_and_recipe(monkeypatch, tmp_path):
    import shadow.quant as q
    monkeypatch.setenv("SHADOW_MODELS_DIR", str(tmp_path))
    base = q.int8_cache_path("m-transformers4.57.0")
    assert base.parent == tmp_path / "int8"
    assert q.int8_cache_path("m-transformers4.58.0") != base           # library version (char-CTC: transformers)
    assert q.int8_cache_path("mms-torchaudio2.11") != q.int8_cache_path("mms-torchaudio2.12")
    monkeypatch.setattr(q, "QUANT_FORMAT", q.QUANT_FORMAT + 1)
    assert q.int8_cache_path("m-transformers4.57.0") != base           # recipe
    monkeypatch.setattr(torch, "__version__", "0.0.0")
    assert "torch0.0.0" in q.int8_cache_path("m").name


def test_quantize_linear_leaves_subclasses_and_handles_shared_weights():
    class Sub(torch.nn.Linear):
        pass
    torch.manual_seed(0)
    a, b = torch.nn.Linear(8, 8), torch.nn.Linear(8, 8)
    b.weight = a.weight                                                # tied
    m = torch.nn.Sequential(a, torch.nn.ReLU(), b, Sub(8, 8))
    x = torch.randn(2, 8)
    ref = m(x)
    q = quantize_linear(m)
    assert isinstance(q[0], torch.ao.nn.quantized.dynamic.Linear) and isinstance(q[2], torch.ao.nn.quantized.dynamic.Linear)
    assert type(q[3]) is Sub
    assert torch.allclose(q(x), ref, atol=0.1)


def test_no_checkpoint_copy_is_restored_and_a_noop_without_funasr(monkeypatch):
    import copy, sys, types
    from shadow.ingest.asr import _no_checkpoint_copy
    mod = types.ModuleType("funasr.train_utils.load_pretrained_model")
    mod.copy = copy
    monkeypatch.setitem(sys.modules, "funasr", types.ModuleType("funasr"))
    monkeypatch.setitem(sys.modules, "funasr.train_utils", types.ModuleType("funasr.train_utils"))
    monkeypatch.setitem(sys.modules, "funasr.train_utils.load_pretrained_model", mod)
    obj = [1]
    with _no_checkpoint_copy():
        assert mod.copy.deepcopy(obj) is obj and mod.copy.copy is copy.copy
    assert mod.copy is copy and copy.deepcopy(obj) is not obj
    monkeypatch.setitem(sys.modules, "funasr.train_utils.load_pretrained_model", None)     # import fails
    with _no_checkpoint_copy():
        pass


def test_a_new_copy_removes_the_stale_copies_of_the_same_model_only(monkeypatch, tmp_path):
    import shadow.quant as q
    monkeypatch.setenv("SHADOW_MODELS_DIR", str(tmp_path))
    d = tmp_path / "int8"
    d.mkdir()
    stale = [d / "m-transformers4.56.0-q1-torch2.10.0.pt", d / "m-transformers4.57.0-q0-torch2.11.0+cpu.pt"]
    other = [d / "other-transformers4.57.0-q1-torch2.11.0.pt", d / "m-x-transformers4.57.0-q1-torch2.11.0.pt",
             d / "notes.txt"]
    for f in stale + other:
        f.write_bytes(b"x")
    cached_int8("m-transformers4.57.0", lambda: quantize_linear(tiny()))
    assert q.int8_cache_path("m-transformers4.57.0").exists()
    assert not any(f.exists() for f in stale)
    assert all(f.exists() for f in other)
    cached_int8("m-transformers4.57.0", lambda: pytest.fail("rebuilt"))        # the new copy stays
