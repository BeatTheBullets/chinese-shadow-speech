import pytest

torch = pytest.importorskip("torch")

from shadow.quant import Int8Linear, cached_int8, quantize_linear


def tiny():
    torch.manual_seed(0)
    return torch.nn.Sequential(torch.nn.Linear(16, 32), torch.nn.GELU(), torch.nn.Linear(32, 4))


def test_quantize_linear_matches_symmetric_per_row_weight_only_int8():
    """Each weight row is rounded to int8 steps of max|row| / 127; the activations and the bias stay fp32."""
    x = torch.randn(3, 16)
    ref = tiny().eval()
    with torch.no_grad():
        for m in ref.modules():
            if type(m) is torch.nn.Linear:
                s = m.weight.abs().amax(dim=1, keepdim=True) / 127
                m.weight.copy_(torch.round(m.weight / s).clamp(-127, 127) * s)
    got = quantize_linear(tiny())(x)
    assert torch.allclose(ref(x), got, atol=1e-6)


def stack():
    torch.manual_seed(0)
    return torch.nn.Sequential(torch.nn.Linear(256, 512), torch.nn.ReLU(), torch.nn.Linear(512, 256), torch.nn.ReLU(),
                               torch.nn.Linear(256, 64))


def test_quantised_tensors_are_int8_weights_and_fp32_scales_and_biases_only():
    fp32_bytes = sum(t.numel() * t.element_size() for t in stack().state_dict().values())
    q = quantize_linear(stack())
    tensors = q.state_dict()
    assert set(tensors) == {f"{i}.{n}" for i in (0, 2, 4) for n in ("weight", "scale", "bias")}
    for name, t in tensors.items():
        assert t.dtype == (torch.int8 if name.endswith("weight") else torch.float32), name
    weights = sum(t.numel() for n, t in tensors.items() if n.endswith("weight"))
    rows = sum(t.numel() for n, t in tensors.items() if n.endswith("bias"))
    total = sum(t.numel() * t.element_size() for t in tensors.values())
    assert total == weights + 2 * 4 * rows                       # int8 weights, an fp32 scale and bias per output row
    assert total < 0.26 * fp32_bytes
    assert not [p for p in q.parameters()]                       # no fp32 weight (or any parameter) left behind


def test_quantised_outputs_do_not_depend_on_the_quantised_engine(monkeypatch):
    x = torch.randn(5, 256)
    outs = []
    for engine in torch.backends.quantized.supported_engines:
        if engine == "none":
            continue
        monkeypatch.setattr(torch.backends.quantized, "engine", engine)
        outs.append(quantize_linear(stack())(x))
    assert outs and all(torch.equal(outs[0], o) for o in outs[1:])


def test_a_weight_row_of_zeros_gives_finite_outputs():
    m = torch.nn.Linear(8, 4)
    with torch.no_grad():
        m.weight[1] = 0
    x = torch.randn(3, 8)
    ref = m(x)
    q = quantize_linear(torch.nn.Sequential(m))
    out = q(x)
    assert torch.isfinite(out).all() and torch.isfinite(q[0].scale).all() and (q[0].scale > 0).all()
    assert torch.equal(out[:, 1], ref[:, 1])                     # the bias alone
    assert torch.allclose(out, ref, atol=0.02)


def test_cached_int8_second_load_gives_identical_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("SHADOW_MODELS_DIR", str(tmp_path))
    x = torch.randn(3, 16)
    calls = []

    def build():
        calls.append(1)
        return quantize_linear(tiny())

    first = cached_int8("tiny", build)(x)
    loaded = cached_int8("tiny", build)
    assert len(calls) == 1 and torch.equal(first, loaded(x))
    assert type(loaded[0]) is Int8Linear and loaded[0].weight.dtype == torch.int8


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
    assert type(q[0]) is Int8Linear and type(q[2]) is Int8Linear
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


def test_the_new_recipe_removes_the_first_recipes_copy(monkeypatch, tmp_path):
    import re
    import shadow.quant as q
    monkeypatch.setenv("SHADOW_MODELS_DIR", str(tmp_path))
    assert q.QUANT_FORMAT >= 2
    d = tmp_path / "int8"
    d.mkdir()
    torch_part = re.sub(r"[^A-Za-z0-9._-]", "_", torch.__version__)
    old = d / f"m-transformers4.57.0-q1-torch{torch_part}.pt"
    old.write_bytes(b"x")
    cached_int8("m-transformers4.57.0", lambda: quantize_linear(tiny()))
    assert f"-q{q.QUANT_FORMAT}-" in q.int8_cache_path("m-transformers4.57.0").name
    assert q.int8_cache_path("m-transformers4.57.0").exists() and not old.exists()
