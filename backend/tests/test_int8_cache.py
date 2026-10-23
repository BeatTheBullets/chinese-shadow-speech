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
    monkeypatch.setenv("HF_HOME", str(tmp_path))
    x = torch.randn(3, 16)
    calls = []

    def build():
        calls.append(1)
        return quantize_linear(tiny())

    first = cached_int8("tiny", build)(x)
    second = cached_int8("tiny", build)(x)
    assert len(calls) == 1 and torch.equal(first, second)
