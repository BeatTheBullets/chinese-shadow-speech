import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location("int8_check", Path(__file__).parents[1] / "scripts" / "int8_check.py")
ic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ic)


def test_verdict_edges():
    assert ic.verdict_of(0.24, 0.25, 0.55) == "different"
    assert ic.verdict_of(0.25, 0.25, 0.55) == "some"
    assert ic.verdict_of(0.54, 0.25, 0.55) == "some"
    assert ic.verdict_of(0.55, 0.25, 0.55) == "clean"


def test_agreement():
    assert ic.agreement(["a", "b", "c", "c"], ["a", "b", "c", "a"]) == 0.75
    assert ic.agreement([], []) == 1.0
    with pytest.raises(ValueError):
        ic.agreement(["a"], [])


def test_cer_ignores_punctuation_and_pools():
    assert ic.cer(["你好，世界。"], ["你好 世界"]) == 0.0
    assert ic.cer(["你好世界"], ["你好世"]) == 0.25
    assert ic.cer(["abcd", "ef"], ["abcd", "xx"]) == pytest.approx(2 / 6)
    assert ic.cer([], []) == 0.0


def test_cache_key_separates_what_shapes_the_result():
    k = ic.cache_key
    assert k("words", "fp32-cuda") != k("words", "fp32-cpu") != k("words", "int8-cpu")
    assert k("words", "fp32-cpu", limit=20) != k("words", "fp32-cpu")
    assert k("words", "int8-cpu", model="iic/paraformer-large") != k("words", "int8-cpu", model="iic/other")
    assert k("align", "int8-cpu", lesson=1) != k("align", "int8-cpu", lesson=2)
    assert k("cer", "int8-cpu", video="abc") != k("cer", "int8-cpu", video="def")
    assert k("words", "fp32-cpu", model="a/b c", limit=5) == "words-fp32-cpu-b_c-limit5.json"


def test_pair_comparison():
    v = {"fp32-cuda": ["clean", "some", "clean", "different"], "fp32-cpu": ["clean", "some", "clean", "some"],
         "int8-cpu": ["clean", "clean", "clean", "different"]}
    got = ic.compare_verdicts(v, [("fp32-cuda", "fp32-cpu"), ("fp32-cpu", "int8-cpu")])
    assert got == [("fp32-cuda", "fp32-cpu", 0.75), ("fp32-cpu", "int8-cpu", 0.5)]
    assert ic.parse_pair("fp32-cuda:int8-cpu") == ("fp32-cuda", "int8-cpu")
    with pytest.raises(ValueError):
        ic.parse_pair("nope")
