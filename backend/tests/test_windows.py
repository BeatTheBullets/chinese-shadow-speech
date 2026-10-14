import pytest
from shadow.scoring.windows import windows


def test_window_runs_to_the_next_start():
    assert windows([(0.0, 0.1), (0.25, 0.3)], dur=1.0) == [(0.0, 0.25), (0.25, pytest.approx(0.45))]


def test_pause_caps_the_window_at_span_end_plus_tail():
    w = windows([(0.0, 0.1), (0.9, 1.0)], dur=2.0)            # next start 0.9 is > 0.5 after 0.0
    assert w[0] == (0.0, pytest.approx(0.25))


def test_last_window_never_passes_the_audio_end_and_never_ends_before_its_span():
    assert windows([(0.0, 0.2)], dur=0.3) == [(0.0, pytest.approx(0.3))]
    assert windows([(0.0, 0.7), (0.8, 0.9)], dur=1.0)[0] == (0.0, pytest.approx(0.8))   # long span: next start
    assert windows([(0.0, 0.2), (0.1, 0.3)], dur=1.0)[0] == (0.0, 0.2)                  # overlap: own end
