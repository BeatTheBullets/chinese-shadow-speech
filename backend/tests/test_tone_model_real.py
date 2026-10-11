import pytest
from shadow.config import ScoringCfg, load_settings
from shadow.ingest.align import FakeAligner
from shadow.scoring.embed import Wav2Vec2Embedder
from shadow.scoring.pitch import baseline_of, track_pitch
from shadow.scoring.score import RefData, score_take
from shadow.scoring.tone import load_tone_model
from tests.helpers import voice

pytestmark = pytest.mark.models
SR, TEXT = 16000, "妈麻马骂"                                   # mā má mǎ mà
SYLS = [{"ch": c, "pinyin": "ma", "pinyin_toneless": "ma", "tone": t} for c, t in zip(TEXT, [1, 2, 3, 4])]
SHAPES = [(240, 240), (170, 250), (150, 125), (260, 140)]


def _score(model, embedder, ref, shapes):
    return score_take(ref=ref, syllables=SYLS, text=TEXT, wav=voice(shapes, syl_s=0.3), sr=SR, aligner=FakeAligner(),
                      embedder=embedder, model=model, profile=None, profile_voiced_s=0.0, cfg=ScoringCfg()).json["syllables"]


def test_real_model_flags_a_flattened_fourth_tone_and_nothing_in_a_copy():
    model = load_tone_model("tone_v1")
    assert model is not None
    st = load_settings()
    m = st.models
    embedder = Wav2Vec2Embedder(m.tone_embedder, m.tone_embedder_revision, m.tone_layer, st.resolved_device())
    ref_wav = voice(SHAPES, syl_s=0.3)
    p = track_pitch(ref_wav, SR)
    ref = RefData(p, [(s.start, s.end) for s in FakeAligner().align(ref_wav, SR, TEXT)], baseline_of(p.voiced()), ref_wav, SR)
    copy = _score(model, embedder, ref, SHAPES)
    print([(s["ch"], s["status"], s["heard_tone"]) for s in copy])
    assert all(s["status"] != "wrong" for s in copy)
    flat = _score(model, embedder, ref, SHAPES[:3] + [(240, 240)])
    print([(s["ch"], s["status"], s["heard_tone"]) for s in flat])
    assert flat[3]["status"] != "ok"
