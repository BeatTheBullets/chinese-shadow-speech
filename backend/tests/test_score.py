import numpy as np
import pytest
from shadow.config import ScoringCfg
from shadow.ingest.align import FakeAligner, Span
from shadow.scoring.embed import FakeEmbedder
from shadow.scoring.pitch import baseline_of, track_pitch
from shadow.scoring.score import RefData, score_take
from shadow.scoring.tone import FakeToneModel
from tests.helpers import voice

SR, CFG = 16000, ScoringCfg(min_rms_dbfs=-45.0, min_align_conf=0.2)   # explicit: the defaults are tuned to the user's takes
TEXT = "今天中心"                                   # jīn tiān zhōng xīn: all tone 1
SYLS = [{"ch": c, "pinyin": p, "pinyin_toneless": p, "tone": 1} for c, p in zip(TEXT, ["jin", "tian", "zhong", "xin"])]
REF_CONTOURS = [(220, 220), (150, 300), (300, 150), (220, 220)]


def ref_data(contours=REF_CONTOURS):
    wav = voice(contours)
    p = track_pitch(wav, SR)
    spans = [(s.start, s.end) for s in FakeAligner().align(wav, SR, TEXT)]
    return RefData(p, spans, baseline_of(p.voiced()), wav, SR)


def run(take, *, syllables=SYLS, text=TEXT, model=FakeToneModel(tone=1, p=0.9), aligner=FakeAligner(), hear=None, sounds=None, ref_key="", **kw):
    return score_take(ref=ref_data(), syllables=syllables, text=text, wav=take, sr=SR, aligner=aligner, model=model,
                      embedder=FakeEmbedder(), profile=kw.get("profile"), profile_voiced_s=kw.get("voiced_s", 0.0), cfg=CFG,
                      hear=hear, sounds=sounds, ref_key=ref_key)


def test_matching_take_is_all_ok():
    r = run(voice(REF_CONTOURS))
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
                   aligner=FakeAligner(), model=FakeToneModel(), embedder=FakeEmbedder(), profile=None, profile_voiced_s=0.0,
                   cfg=CFG)
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


def test_pitch_unvoiced_syllable_is_still_judged_without_contour(monkeypatch):
    import shadow.scoring.score as score
    real = score.syllable_pitch
    def no_pitch_on_third(norm, t0, start, end, min_voiced):          # pretend syllable 3 has no voiced frames
        s = real(norm, t0, start, end, min_voiced)
        return score.SylPitch(None, 0.0, s.duration) if 0.5 <= start < 0.75 else s
    monkeypatch.setattr(score, "syllable_pitch", no_pitch_on_third)
    syl = run(voice(REF_CONTOURS)).json["syllables"][2]
    assert syl["status"] in ("ok", "close") and syl["contour"] is None and syl["tone_score"] == pytest.approx(syl["p_target"])


def test_a_take_of_the_sentence_is_scored_with_what_was_heard():
    r = run(voice(REF_CONTOURS), hear=lambda: "今天中心。")
    assert r.json["warnings"] == [] and r.json["overall"] is not None and r.rows
    assert r.json["heard_text"] == "今天中心。" and r.json["quality"]["text_sim"] == 1.0 and r.json["notices"] == []


def test_a_take_of_other_words_is_not_scored():
    r = run(voice(REF_CONTOURS), hear=lambda: "我是学生。")
    assert r.json["warnings"] == ["different_words"] and r.json["overall"] is None and r.rows == []
    assert r.json["heard_text"] == "我是学生。" and r.json["quality"]["text_sim"] == 0.0
    assert r.json["model_version"] == "fake" and r.json["notices"] == []


def test_silence_is_never_transcribed():
    def hear(): raise AssertionError("hear called")
    r = run(np.zeros(SR, dtype="float32"), hear=hear)
    assert "too_quiet" in r.json["warnings"] and r.json["heard_text"] is None and r.json["quality"]["text_sim"] is None


def test_without_a_hearer_the_words_are_not_checked():
    r = run(voice(REF_CONTOURS))
    assert r.json["warnings"] == [] and r.json["heard_text"] is None and r.json["quality"]["text_sim"] is None


def test_a_busy_recogniser_skips_the_words_check():
    r = run(voice(REF_CONTOURS), hear=lambda: None)
    assert r.json["warnings"] == [] and r.json["overall"] is not None
    assert r.json["heard_text"] is None and r.json["quality"]["text_sim"] is None


def test_a_take_with_some_words_different_is_scored_with_a_notice():
    """Between min_text_similarity and words_ok_at: a few misheard words, still the sentence (spec §1)."""
    r = run(voice(REF_CONTOURS), hear=lambda: "今天。")                  # 2 of 4 syllables: 0.5
    assert r.json["quality"]["text_sim"] == 0.5 and r.json["overall"] is not None and r.rows
    assert r.json["warnings"] == [] and r.json["notices"] == ["words_differ"]


def test_a_take_without_a_words_check_has_no_notices():
    assert run(voice(REF_CONTOURS)).json["notices"] == []
    assert run(np.zeros(SR, dtype="float32")).json["notices"] == []


@pytest.mark.parametrize("sim, warnings, notices", [(0.249, ["different_words"], []), (0.25, [], ["words_differ"]),
                                                    (0.549, [], ["words_differ"]), (0.55, [], [])])
def test_the_words_check_band_edges(monkeypatch, sim, warnings, notices):
    import shadow.scoring.score as score
    monkeypatch.setattr(score, "text_similarity", lambda syllables, heard: sim)
    cfg = CFG.model_copy(update={"min_text_similarity": 0.25, "words_ok_at": 0.55})
    r = score_take(ref=ref_data(), syllables=SYLS, text=TEXT, wav=voice(REF_CONTOURS), sr=SR, aligner=FakeAligner(),
                   model=FakeToneModel(tone=1, p=0.9), embedder=FakeEmbedder(), profile=None, profile_voiced_s=0.0,
                   cfg=cfg, hear=lambda: "…")
    assert r.json["warnings"] == warnings and r.json["notices"] == notices


def _slip():
    return {"status": "slip", "heard": "zhong", "heard_pinyin": "zhōng", "z": 7.5, "rule": "fused"}


def _ok():
    return {"status": "ok", "heard": None, "heard_pinyin": None, "z": -1.0, "rule": "fused"}


def test_score_take_stores_sound_results():
    from shadow.scoring.sounds.detector import FakeSounds
    take = voice(REF_CONTOURS)
    plain = run(take)
    r = run(take, sounds=FakeSounds([_ok(), _slip(), None, None]), ref_key="k")
    assert r.json["syllables"][1]["sound"]["heard_pinyin"] == "zhōng"
    assert r.json["syllables"][0]["sound"]["status"] == "ok" and r.json["syllables"][2]["sound"] is None
    assert r.json["sounds_off"] == 1 and r.json["sounds_checked"] == 2
    assert r.rows[1]["sound_status"] == "slip" and r.rows[1]["heard_syllable"] == "zhong" and r.rows[1]["seg_score"] == 7.5
    assert r.rows[0]["sound_status"] == "ok" and r.rows[2]["sound_status"] is None
    assert r.json["overall"] == plain.json["overall"]
    assert plain.json["sounds_off"] is None and plain.json["sounds_checked"] is None


def test_sound_failure_keeps_tone_score():
    from shadow.scoring.sounds.detector import FakeSounds
    take = voice(REF_CONTOURS)
    plain = run(take)
    r = run(take, sounds=FakeSounds(error=True), ref_key="k")
    assert r.json["overall"] == plain.json["overall"] and r.json["tone_overall"] == plain.json["tone_overall"]
    assert r.json["sounds_off"] is None and r.json["sounds_checked"] is None
    assert all(s["sound"] is None for s in r.json["syllables"])
    assert all(row["sound_status"] is None for row in r.rows)


def test_sounds_get_the_trimmed_take_and_its_windows():
    class Spy:
        def check(self, **kw):
            self.kw = kw
            return [None] * len(kw["syllables"])
    spy = Spy()
    take = voice(REF_CONTOURS, lead_s=0.4)
    run(take, sounds=spy, ref_key="k")
    assert len(spy.kw["take"]) < len(take) and len(spy.kw["usr_win"]) == 4 and spy.kw["ref_key"] == "k"
    assert spy.kw["statuses"] == ["ok"] * 4


def test_a_malformed_sound_result_keeps_tone_score():
    from shadow.scoring.sounds.detector import FakeSounds
    take = voice(REF_CONTOURS)
    plain = run(take)
    for bad in ([_ok()], [_ok(), {"status": "slip"}, None, None]):       # wrong length; a dict missing keys
        r = run(take, sounds=FakeSounds(bad), ref_key="k")
        assert r.json["overall"] == plain.json["overall"]
        assert r.json["sounds_off"] is None and r.json["sounds_checked"] is None
        assert all(x["sound"] is None for x in r.json["syllables"])
        assert all(row["sound_status"] is None and row["heard_syllable"] is None and row.get("seg_score") is None
                   for row in r.rows)
