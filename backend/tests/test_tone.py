import json
import numpy as np
import pytest
from shadow.config import ScoringCfg
from shadow.scoring.tone import (TONES, FakeToneModel, contour_similarity, judge, load_tone_model, sentence_overall,
                                 target_tone)

CFG = ScoringCfg()


def p_of(**probs):
    row = np.zeros(5)
    for k, v in probs.items():
        row[TONES.index(int(k[1:]))] = v
    return row


def test_fake_model_shape_and_order():
    P = FakeToneModel(tone=3, p=0.8).proba(np.zeros((2, 45)))
    assert P.shape == (2, 5) and np.allclose(P.sum(axis=1), 1.0) and P[0, TONES.index(3)] == pytest.approx(0.8)


def test_target_tone_uses_a_confident_reference_else_canonical():
    assert target_tone(p_of(t2=0.7, t3=0.3), canonical=3, min_conf=0.6) == 2     # 3-3 sandhi heard as 2
    assert target_tone(p_of(t2=0.5, t3=0.5), canonical=3, min_conf=0.6) == 3
    assert target_tone(None, canonical=4, min_conf=0.6) == 4


def test_contour_similarity_is_scaled_and_clamped():
    a = np.zeros(20)
    assert contour_similarity(a, a, 4, norm=1.0) == 1.0
    assert contour_similarity(a, a + 0.1, 4, norm=1.0) == pytest.approx(0.9)
    assert contour_similarity(a, a + 5, 4, norm=1.0) == 0.0


def test_judge_ok_close_wrong():
    ok = judge(p_of(t4=0.9, t1=0.1), target=4, contour=0.9, cfg=CFG)
    assert (ok.status, ok.heard) == ("ok", 4) and ok.tone_score == pytest.approx(0.9)
    close = judge(p_of(t4=0.6, t1=0.4), target=4, contour=0.3, cfg=CFG)
    assert close.status == "close" and close.tone_score == pytest.approx(0.45)
    wrong = judge(p_of(t2=0.8, t3=0.2), target=3, contour=0.4, cfg=CFG)
    assert (wrong.status, wrong.heard) == ("wrong", 2)
    unsure = judge(p_of(t2=0.5, t3=0.4, t1=0.1), target=3, contour=0.9, cfg=CFG)
    assert unsure.status == "close"                    # another tone wins, but by less than wrong_margin


def test_judge_neutral_target_ignores_contour():
    v = judge(p_of(t0=0.8, t1=0.2), target=0, contour=0.0, cfg=CFG)
    assert v.tone_score == pytest.approx(0.8) and v.status == "ok"


def test_sentence_overall():
    assert sentence_overall([("ok", 0.9), ("missing", None), ("unvoiced", None), ("close", 0.6)]) == pytest.approx(0.5)
    assert sentence_overall([("unvoiced", None)]) is None
    assert sentence_overall([]) is None


def test_load_tone_model_rejects_missing_and_mismatched(tmp_path):
    assert load_tone_model("nope", tmp_path) is None
    (tmp_path / "m.json").write_text(json.dumps({"version": "m", "feature_version": 999, "dtw_norm": 1.0}))
    (tmp_path / "m.joblib").write_bytes(b"x")
    assert load_tone_model("m", tmp_path) is None


def test_load_tone_model_reorders_classes(tmp_path):
    import joblib
    from sklearn.dummy import DummyClassifier
    from shadow.scoring.features import FEATURE_VERSION
    X = np.zeros((5, 3)); y = np.array([4, 3, 2, 1, 0])
    clf = DummyClassifier(strategy="prior").fit(X, y)
    joblib.dump(clf, tmp_path / "m.joblib")
    (tmp_path / "m.json").write_text(json.dumps({"version": "m1", "feature_version": FEATURE_VERSION, "dtw_norm": 2.0}))
    m = load_tone_model("m", tmp_path)
    assert m.version == "m1" and m.dtw_norm == 2.0 and m.proba(np.zeros((1, 3))).shape == (1, 5)


def test_a_corrupt_tone_model_is_none_not_a_crash(tmp_path):
    """build_deps loads it at start-up: an unreadable file must not stop the server (scores say no_tone_model)."""
    from shadow.scoring.features import FEATURE_VERSION
    (tmp_path / "m.json").write_text(json.dumps({"version": "m", "feature_version": FEATURE_VERSION, "dtw_norm": 1.0}))
    (tmp_path / "m.joblib").write_bytes(b"not a pickle")
    assert load_tone_model("m", tmp_path) is None
    (tmp_path / "m.json").write_text("{not json")
    assert load_tone_model("m", tmp_path) is None
