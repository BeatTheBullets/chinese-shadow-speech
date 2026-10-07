import numpy as np
from shadow.ingest.align import Span
from shadow.ingest.aligncheck import OnsetError, energy_onset, onset_error, verdict, zero_length_share


def test_energy_onset_finds_the_first_loud_frame():
    sr = 16000
    wav = np.zeros(sr * 2, dtype="float32")
    wav[int(0.8 * sr):int(1.5 * sr)] = 0.3 * np.sin(np.arange(int(0.7 * sr)) * 0.2)
    assert abs(energy_onset(wav, sr, 0.0, 2.0) - 0.8) <= 0.02
    assert energy_onset(np.zeros(sr, dtype="float32"), sr, 0.0, 1.0) is None     # silence
    assert energy_onset(wav, sr, 1.99, 2.0) is None                               # shorter than one frame


def test_zero_length_share():
    assert zero_length_share([[Span("我", 1.0, 1.0, 1.0), Span("好", 1.0, 1.2, 1.0)], []]) == 0.5
    assert zero_length_share([]) == 0.0


def test_onset_error_skips_missing_values():
    e = onset_error([1.05, None, 2.5], [1.0, 3.0, 2.0])
    assert (e.n, e.mean_ms, e.median_ms, e.within_100ms) == (2, 275.0, 275.0, 0.5)


def test_verdict_needs_mms_clearly_better():
    q = OnsetError(50, 200.0, 150.0, 0.4)
    assert verdict(q, 0.3, OnsetError(50, 120.0, 90.0, 0.7), 0.0) == "mms_fa"
    assert verdict(q, 0.3, OnsetError(50, 150.0, 90.0, 0.7), 0.0) == "qwen3_fa"     # only 25 % better
    assert verdict(q, 0.0, OnsetError(50, 100.0, 90.0, 0.7), 0.1) == "qwen3_fa"     # more zero-length spans
