import pytest

from shadow.ingest.asr import transcript_from_funasr, FakeASR
from shadow.ingest.text import is_punct
from shadow.ingest.transcript import Transcript


def test_funasr_sentence_info_with_matching_timestamps():
    result = {
        "text": "你好，世界。再见。",
        "sentence_info": [
            {"text": "你好，世界。", "start": 1000, "end": 2000,
             "timestamp": [[1000, 1200], [1200, 1400], [1500, 1700], [1700, 2000]]},
            {"text": "再见。", "start": 2500, "end": 3000, "timestamp": [[2500, 2700], [2700, 3000]]},
        ],
    }
    tr = transcript_from_funasr(result)
    assert tr.text == "你好，世界。再见。"
    assert tr.chars[0].start == 1.0 and tr.chars[3].end == 1.7 and tr.chars[4].end == 2.0
    assert tr.chars[2].start == tr.chars[2].end == 1.4           # comma zero-length
    assert tr.segments == [(0, 5), (6, 8)]


def test_funasr_timestamp_count_mismatch_falls_back_to_interpolation():
    result = {"text": "你好世界", "sentence_info": [{"text": "你好世界", "start": 0, "end": 2000, "timestamp": [[0, 500]]}]}
    tr = transcript_from_funasr(result)
    assert [round(c.start, 2) for c in tr.chars] == [0.0, 0.5, 1.0, 1.5]


def test_funasr_without_sentence_info_uses_whole_text():
    tr = transcript_from_funasr({"text": "大家好", "timestamp": [[0, 300], [300, 600], [600, 900]]})
    assert tr.text == "大家好" and tr.chars[2].end == 0.9 and tr.segments == [(0, 2)]


# FunASR 1.4.16 glues the last char of one VAD chunk to the first of the next ("视那"), so its sentence_info runs
# one char ahead of its timestamps after each chunk boundary; the top-level text + timestamp pair up 1:1.
_GLUED = {
    "text": "他在看电视，那是小王。",
    "timestamp": [[i * 100, i * 100 + 80] for i in range(5)] + [[1000 + i * 100, 1080 + i * 100] for i in range(4)],
    "sentence_info": [
        {"text": "他在看电视那，", "start": 0, "end": 480,
         "timestamp": [[i * 100, i * 100 + 80] for i in range(5)]},
        {"text": "是小王。", "start": 1000, "end": 1380,
         "timestamp": [[1000 + i * 100, 1080 + i * 100] for i in range(4)]},
    ],
}


def test_funasr_chars_are_timed_by_the_top_level_text_not_the_drifted_sentence_info():
    tr = transcript_from_funasr(_GLUED)
    speech = [c for c in tr.chars if not is_punct(c.c)]
    assert "".join(c.c for c in speech) == "他在看电视那是小王"
    assert speech[5].c == "那" and speech[5].start == 1.0
    assert [(c.start, c.end) for c in speech] == [(a / 1000, b / 1000) for a, b in _GLUED["timestamp"]]
    comma, period = tr.chars[5], tr.chars[10]
    assert (comma.c, comma.start, comma.end) == ("，", 0.48, 0.48)      # zero-length at the previous char's end
    assert (period.c, period.start, period.end) == ("。", 1.38, 1.38)
    assert tr.segments == [(0, 10)]                  # sentence ranges: a comma does not end one


def test_funasr_segments_split_at_sentence_final_punctuation():
    tr = transcript_from_funasr({"text": "你好。再见！”好", "timestamp": [[i * 100, i * 100 + 90] for i in range(5)]})
    assert tr.segments == [(0, 2), (3, 6), (7, 7)]   # a closing quote stays with its sentence


def test_funasr_real_excerpt_at_a_vad_boundary_is_timed_by_the_top_level_timestamps():
    import json
    from pathlib import Path
    r = json.loads(Path(__file__).parents[1].joinpath("fixtures/funasr_lesson2_excerpt.json").read_text())
    tr = transcript_from_funasr(r)
    speech = [c for c in tr.chars if not is_punct(c.c)]
    assert "".join(c.c for c in speech) == "她们看电视那是我的朋友小王"
    assert [(c.start, c.end) for c in speech] == [(a / 1000, b / 1000) for a, b in r["timestamp"]]
    assert speech[5].c == "那" and speech[5].start == 58.47


def test_funasr_top_level_count_mismatch_falls_back_to_sentence_info_with_a_warning(caplog):
    r = {**_GLUED, "timestamp": _GLUED["timestamp"][:8]}
    with caplog.at_level("WARNING"):
        tr = transcript_from_funasr(r)
    assert "9 speech characters" in caplog.text and "8 timestamps" in caplog.text
    assert tr.segments == [(0, 6), (7, 10)]          # the sentence_info path


def test_funasr_interpolated_sentence_times_are_logged(caplog):
    with caplog.at_level("WARNING"):
        transcript_from_funasr({"text": "你好世界", "sentence_info": [
            {"text": "你好世界", "start": 0, "end": 2000, "timestamp": [[0, 500]]}]})
    assert "interpolat" in caplog.text


def test_funasr_empty_text_gives_empty_transcript():
    tr = transcript_from_funasr({"text": "", "sentence_info": []})
    assert tr.chars == [] and tr.segments == []


def test_fake_asr_returns_given_transcript(tmp_path):
    tr = Transcript()
    assert FakeASR(tr).transcribe(tmp_path / "x.wav") is tr


@pytest.mark.models
def test_paraformer_real(tmp_path):
    from shadow.ingest.asr import ParaformerASR
    from tests.helpers import make_tone_wav
    asr = ParaformerASR("iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch", "cpu")
    tr = asr.transcribe(make_tone_wav(tmp_path / "t.wav", 2.0))
    assert isinstance(tr, Transcript)


def test_asr_hearer_returns_the_recognised_text_with_punctuation(tmp_path):
    from shadow.ingest.asr import AsrHearer, FakeHearer, ParaformerASR
    class Gen:
        def generate(self, **kw): return [{"text": "我是学生。", "timestamp": [[0, 100], [100, 200], [200, 300], [300, 400]]}]
    asr = ParaformerASR("none", "cpu"); asr._model = Gen()
    assert AsrHearer(asr).hear(tmp_path / "x.wav") == "我是学生。"
    assert FakeHearer("你好").hear(tmp_path / "x.wav") == "你好"


def test_paraformer_calls_run_one_at_a_time(tmp_path):
    """Ingest jobs and attempt scoring share one recogniser."""
    import threading, time
    from shadow.ingest.asr import ParaformerASR

    class Slow:
        def __init__(self): self.active = 0; self.peak = 0
        def generate(self, **kw):
            self.active += 1; self.peak = max(self.peak, self.active); time.sleep(0.05); self.active -= 1
            return [{"text": ""}]

    asr = ParaformerASR("none", "cpu"); asr._model = inner = Slow()
    ts = [threading.Thread(target=asr.transcribe, args=(tmp_path / "x.wav",)) for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert inner.peak == 1


def _client_with_asr(data_dir, asr):
    from fastapi.testclient import TestClient
    from shadow.config import Settings
    from shadow.deps import fake_deps
    from shadow.main import create_app
    s = Settings(data_dir=data_dir)
    deps = fake_deps(s, Transcript()); deps.asr = asr
    return TestClient(create_app(s, deps=deps))


def test_the_recogniser_warms_up_at_start_up(data_dir, monkeypatch):
    import threading
    from shadow.ingest.asr import ParaformerASR
    loaded = threading.Event()

    def load(self):
        assert self._lock.locked(); loaded.set()
    monkeypatch.setattr(ParaformerASR, "_load", load)
    with _client_with_asr(data_dir, ParaformerASR("none", "cpu")):
        assert loaded.wait(5)


def test_a_failed_recogniser_warm_up_is_logged_not_raised(data_dir, monkeypatch, caplog):
    import threading
    from shadow.ingest.asr import ParaformerASR
    tried = threading.Event()

    def load(self):
        tried.set(); raise OSError("offline")
    monkeypatch.setattr(ParaformerASR, "_load", load)
    with _client_with_asr(data_dir, ParaformerASR("none", "cpu")) as c:
        assert tried.wait(5)
        assert c.get("/health").status_code == 200
    for _ in range(50):
        if "warming up" in caplog.text:
            break
        threading.Event().wait(0.02)
    assert "warming up the recogniser" in caplog.text and "offline" in caplog.text


def test_real_deps_hear_takes_with_the_ingest_recogniser_and_fake_deps_do_not(tmp_path):
    from shadow.config import Settings
    from shadow.deps import build_deps, fake_deps
    from shadow.ingest.asr import AsrHearer
    s = Settings(data_dir=tmp_path)
    real = build_deps(s)
    assert isinstance(real.hearer, AsrHearer) and real.hearer.asr is real.asr
    assert fake_deps(s, Transcript()).hearer is None


class _Gen:
    def generate(self, **kw): return [{"text": " lily。"}]


def test_asr_hearer_trims_the_heard_text(tmp_path):
    from shadow.ingest.asr import AsrHearer, ParaformerASR
    asr = ParaformerASR("none", "cpu"); asr._model = _Gen()
    assert AsrHearer(asr).hear(tmp_path / "x.wav") == "lily。"


def test_a_busy_recogniser_is_not_waited_for(tmp_path, monkeypatch):
    """An ingest job holds the recogniser for a whole video: a take does not wait for it, its words go unchecked."""
    import shadow.ingest.asr as asr_mod
    from shadow.ingest.asr import AsrHearer, ParaformerASR
    asr = ParaformerASR("none", "cpu"); asr._model = _Gen()
    assert asr.try_transcribe(tmp_path / "x.wav", 0.01).text == " lily。"
    monkeypatch.setattr(asr_mod, "HEAR_WAIT_S", 0.01)
    with asr._lock:
        assert asr.try_transcribe(tmp_path / "x.wav", 0.01) is None
        assert AsrHearer(asr).hear(tmp_path / "x.wav") is None


def test_unpunctuated_count_mismatch_fallback_is_cut_to_max_chars():
    from shadow.config import SegmentationCfg
    text = "我今天早上去了学校然后和同学一起吃午饭下午又回到教室 A1 认真地学习数学和英语"
    res = {"text": text, "timestamp": [[0, 240]] * 5}      # speech count disagrees with the timestamps
    tr = transcript_from_funasr(res, pauses=SegmentationCfg())
    assert tr.text == "".join(text.split())
    assert len(tr.segments) >= 2
    assert all(b - a + 1 <= 25 for a, b in tr.segments)
    flat = [i for a, b in tr.segments for i in range(a, b + 1)]
    assert flat == list(range(len(tr.chars)))


@pytest.mark.parametrize("punctuation, expected", [(False, None), (True, "ct-punc")])
def test_paraformer_load_passes_punc_model_only_when_punctuation_is_on(monkeypatch, punctuation, expected):
    import sys
    import types
    from shadow.ingest.asr import ParaformerASR
    seen = {}

    class FakeAutoModel:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setitem(sys.modules, "funasr", types.SimpleNamespace(AutoModel=FakeAutoModel))
    ParaformerASR("m", "cpu", punctuation=punctuation)._load()
    assert seen.get("punc_model") == expected
    assert ("punc_model" in seen) == punctuation
    assert seen["model"] == "m" and seen["vad_model"] == "fsmn-vad"
