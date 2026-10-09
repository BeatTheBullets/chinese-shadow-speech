import numpy as np
import pytest
from shadow.config import ScoringCfg
from shadow.ingest.align import FakeAligner, Span
from shadow.scoring.pitch import baseline_of, track_pitch
from shadow.scoring.score import RefData, score_take
from shadow.scoring.tone import FakeToneModel
from tests.helpers import voice

SR, CFG = 16000, ScoringCfg()
TEXT = "今天中心"                                   # jīn tiān zhōng xīn: all tone 1
SYLS = [{"ch": c, "pinyin": p, "pinyin_toneless": p, "tone": 1} for c, p in zip(TEXT, ["jin", "tian", "zhong", "xin"])]
REF_CONTOURS = [(220, 220), (150, 300), (300, 150), (220, 220)]


def ref_data(contours=REF_CONTOURS):
    wav = voice(contours)
    p = track_pitch(wav, SR)
    spans = [(s.start, s.end) for s in FakeAligner().align(wav, SR, TEXT)]
    return RefData(p, spans, baseline_of(p.voiced()))


def run(take, *, syllables=SYLS, text=TEXT, model=FakeToneModel(tone=1, p=0.9), aligner=FakeAligner(), **kw):
    return score_take(ref=ref_data(), syllables=syllables, text=text, wav=take, sr=SR, aligner=aligner, model=model,
                      profile=kw.get("profile"), profile_voiced_s=kw.get("voiced_s", 0.0), cfg=CFG)


def test_matching_take_is_all_ok():
    r = run(voice(REF_CONTOURS, lead_s=0.3))
    assert [s["status"] for s in r.json["syllables"]] == ["ok"] * 4
    assert r.json["overall"] == pytest.approx(r.json["tone_overall"]) and r.json["overall"] > 0.9
    assert r.json["warnings"] == [] and r.json["segmental_overall"] is None
    assert len(r.rows) == 4 and r.rows[1]["prev_tone"] == 1 and r.rows[0]["prev_tone"] is None
    assert len(r.voiced_f0) > 50


def test_an_inverted_syllable_loses_only_its_contour():
    take = voice([(220, 220), (300, 150), (300, 150), (220, 220)])       # syllable 2 falls instead of rising
    syl = run(take).json["syllables"]
    assert syl[1]["contour"] < 0.5 and syl[1]["status"] == "close"
    assert all(syl[i]["status"] == "ok" for i in (0, 2, 3))


def test_usr_contour_is_on_the_stored_take_axis():
    r = run(voice(REF_CONTOURS, lead_s=0.4))
    c = r.json["usr_contour"]
    assert c["step_ms"] == 10 and len(c["spans"]) == 4
    assert 0.35 <= c["spans"][0][0] <= 0.45                              # trim offset added back
    assert c["t0_s"] >= 0.3                                                # the trimmed take starts ~0.35 s in


def test_tiny_take_is_gated_before_pitch(monkeypatch):
    import shadow.scoring.score as score
    monkeypatch.setattr(score, "track_pitch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("pitch called")))
    r = score_take(ref=ref_data(), syllables=SYLS, text=TEXT, wav=voice([(200, 200)], syl_s=0.1), sr=SR,
                   aligner=FakeAligner(), model=FakeToneModel(), profile=None, profile_voiced_s=0.0, cfg=CFG)
    assert r.json["overall"] is None and "too_short" in r.json["warnings"] and r.rows == []
    assert [s["status"] for s in r.json["syllables"]] == ["missing"] * 4


def test_silence_is_too_quiet():
    r = run(np.zeros(SR, dtype="float32"))
    assert "too_quiet" in r.json["warnings"] and r.rows == []


def test_no_model_scores_nothing():
    r = run(voice(REF_CONTOURS), model=None)
    assert r.json["overall"] is None and r.json["warnings"] == ["no_tone_model"] and r.rows == []


def test_span_count_mismatch_is_align_failed():
    class Short:
        def align(self, wav, sr, text): return [Span("今", 0.0, 0.5, 1.0)]
    r = run(voice(REF_CONTOURS), aligner=Short())
    assert r.json["warnings"] == ["align_failed"] and r.json["overall"] is None


def test_low_confidence_alignment_is_wrong_or_unclear():
    class Unsure:
        def align(self, wav, sr, text): return [Span(s.ch, s.start, s.end, 0.05) for s in FakeAligner().align(wav, sr, text)]
    r = run(voice(REF_CONTOURS), aligner=Unsure())
    assert r.json["warnings"] == ["wrong_or_unclear"] and r.json["quality"]["align_conf"] == pytest.approx(0.05)


def test_zero_length_learner_span_is_missing():
    class Collapsed:
        def align(self, wav, sr, text):
            sp = FakeAligner().align(wav, sr, text)
            sp[2] = Span(sp[2].ch, sp[2].start, sp[2].start, 1.0)
            return sp
    r = run(voice(REF_CONTOURS), aligner=Collapsed())
    syl = r.json["syllables"]
    assert syl[2]["status"] == "missing" and syl[2]["tone_score"] == 0.0
    assert r.rows[2]["status"] == "missing"


def test_non_hanzi_syllable_is_unvoiced():
    syls = SYLS[:3] + [{"ch": "A", "pinyin": "A", "pinyin_toneless": "A", "tone": -1}]
    r = run(voice(REF_CONTOURS), syllables=syls, text="今天中A")
    assert r.json["syllables"][3]["status"] == "unvoiced" and r.json["syllables"][3]["tone_score"] is None


def test_wrong_tone_shows_heard_tone():
    r = run(voice(REF_CONTOURS), model=FakeToneModel(tone=2, p=0.9))
    # the reference is also 'heard' as 2 by this fake, so the target becomes 2 and the take matches it
    assert {s["target_tone"] for s in r.json["syllables"]} == {2}
    low_ref = FakeToneModel(tone=2, p=0.55)            # under ref_confidence → canonical target 1
    r2 = run(voice(REF_CONTOURS), model=low_ref)
    s = r2.json["syllables"][0]
    assert s["target_tone"] == 1 and s["heard_tone"] == 2 and s["status"] == "wrong"


def test_profile_sets_the_learner_baseline_once_it_has_enough_speech():
    from shadow.scoring.pitch import Baseline
    take = voice(REF_CONTOURS)
    alone = run(take).json["usr_contour"]["f0_st"]
    with_profile = run(take, profile=Baseline(110.0, 3.0), voiced_s=600.0).json["usr_contour"]["f0_st"]
    a = np.array([v for v in alone if v is not None]); b = np.array([v for v in with_profile if v is not None])
    assert b.mean() > a.mean() + 1                     # a 110 Hz baseline puts a 220 Hz take high above it
