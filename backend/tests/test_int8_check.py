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
