import numpy as np
from shadow.config import ScoringCfg
from shadow.ingest.align import Span
from shadow.scoring.gate import align_gate, clipped_ratio, level_dbfs, pre_gate
from tests.helpers import voice

SR, CFG = 16000, ScoringCfg(min_rms_dbfs=-45.0, min_align_conf=0.2)   # explicit: the defaults are tuned to the user's takes


def test_good_take_passes():
    assert pre_gate(voice([(200, 200)], syl_s=1.0), SR, ref_speech_s=1.2, cfg=CFG) == []


def test_too_short_too_quiet_clipped():
    assert "too_short" in pre_gate(voice([(200, 200)], syl_s=0.3), SR, ref_speech_s=1.0, cfg=CFG)
    assert "too_quiet" in pre_gate(voice([(200, 200)], syl_s=1.0) * 0.001, SR, ref_speech_s=1.0, cfg=CFG)
    loud = np.clip(voice([(200, 200)], syl_s=1.0) * 20, -1, 1)
    assert "clipped" in pre_gate(loud, SR, ref_speech_s=1.0, cfg=CFG)


def test_levels():
    assert level_dbfs(np.zeros(100)) < -100
    assert abs(level_dbfs(np.full(100, 0.5)) - (-6.02)) < 0.1
    assert clipped_ratio(np.array([1.0, -1.0, 0.0, 0.2])) == 0.5


def test_align_gate_on_mean_confidence():
    good = [Span("我", 0, 0.2, 0.8), Span("们", 0.2, 0.4, 0.6)]
    bad = [Span("我", 0, 0.2, 0.1), Span("们", 0.2, 0.4, 0.1)]
    assert align_gate(good, CFG) == [] and align_gate(bad, CFG) == ["wrong_or_unclear"]
