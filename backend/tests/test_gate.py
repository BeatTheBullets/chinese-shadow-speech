import numpy as np
from shadow.config import ScoringCfg
from shadow.ingest.align import Span
from shadow.scoring.gate import align_gate, clipped_ratio, level_dbfs, pre_gate, text_similarity
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


def syls(text):
    from shadow.ingest.enrich import words_for
    return [s for w in words_for(text) for s in w["syllables"]]


def test_text_similarity_compares_toneless_syllables():
    assert text_similarity(syls("我是学生。"), "我是学生。") == 1.0
    assert text_similarity([{"ch": "马", "pinyin_toneless": "ma", "tone": 3}], "妈") == 1.0   # a tone slip, not other words
    assert text_similarity(syls("我是学生"), "今天天气很好") < 0.2
    assert text_similarity(syls("我是学生"), "我是") == 0.5
    assert text_similarity(syls("绿色"), "绿色") == 1.0                                  # ü on both sides


def test_text_similarity_skips_non_hanzi_and_scores_silence_zero():
    assert text_similarity(syls("我有2个A"), "我有个") == 1.0
    assert text_similarity(syls("我有个"), "我有，A个") == 1.0
    assert text_similarity(syls("我是学生"), "") == 0.0


def test_latin_letters_in_what_was_heard_also_compare_letter_by_letter():
    assert text_similarity(syls("丽丽，"), " lily。") >= 0.55              # a name the recogniser spelt in English
    assert text_similarity(syls("我的朋友"), " hello hello") < 0.55
    assert text_similarity(syls("我是学生"), "我是") == 0.5                # no Latin letters: syllables only


def test_the_letter_fallback_needs_a_mostly_latin_transcript():
    assert text_similarity(syls("现在几点了"), "下次见 ok") == text_similarity(syls("现在几点了"), "下次见") < 0.55
    assert text_similarity(syls("丽丽，"), " lily。") >= 0.55
