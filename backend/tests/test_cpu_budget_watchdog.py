import importlib.util
import sys
from pathlib import Path

spec = importlib.util.spec_from_file_location("cpu_budget", Path(__file__).parents[1] / "scripts" / "cpu_budget.py")
cpu_budget = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cpu_budget)

ALLOC = "b = bytearray(400_000_000); b[::4096] = b'x' * len(b[::4096]); import time; time.sleep(30)"


def test_watchdog_kills_child_over_cap(capsys):
    assert cpu_budget.watch([sys.executable, "-c", ALLOC], 150) == 3
    assert "over hard cap" in capsys.readouterr().err


def test_watchdog_passes_exit_code_under_cap(capsys):
    assert cpu_budget.watch([sys.executable, "-c", "raise SystemExit(7)"], 150) == 7
    assert "over hard cap" not in capsys.readouterr().err
