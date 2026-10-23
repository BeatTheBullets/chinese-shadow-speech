import pytest

from shadow.ingest.asr import transcript_from_funasr, FakeASR
from shadow.ingest.text import is_punct
from shadow.ingest.transcript import Transcript


def test_funasr_sentence_info_is_never_used():
    result = {
        "text": "你好，世界。再见。",
        "timestamp": [[1000, 1200], [1200, 1400], [1500, 1700], [1700, 2000], [2500, 2700], [2700, 3000]],
        "sentence_info": [
            {"text": "你好世，界。", "start": 1000, "end": 2000,
             "timestamp": [[1000, 1200], [1200, 1400], [1500, 1700], [1700, 2000]]},
            {"text": "再见。", "start": 2500, "end": 3000, "timestamp": [[2500, 2700], [2700, 3000]]},
        ],
    }
    tr = transcript_from_funasr(result)
    assert tr.text == "你好，世界。再见。"
    assert tr.chars[0].start == 1.0 and tr.chars[3].end == 1.7 and tr.chars[4].end == 2.0
    assert tr.chars[2].start == tr.chars[2].end == 1.4           # comma zero-length
    assert tr.segments == [(0, 5), (6, 8)]


def test_funasr_timestamp_count_mismatch_lays_the_text_over_the_timestamps(caplog):
    with caplog.at_level("WARNING"):
        tr = transcript_from_funasr({"text": "你好世界", "timestamp": [[0, 2000]]})
    assert [round(c.start, 2) for c in tr.chars] == [0.0, 0.5, 1.0, 1.5]
    assert "4 speech characters in 4 timed units for 1 timestamps" in caplog.text


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


def _latin_excerpt():
    import json
    from pathlib import Path
    return json.loads(Path(__file__).parents[1].joinpath("fixtures/funasr_latin_drift_excerpt.json").read_text())


def test_funasr_latin_word_keeps_the_top_level_text_not_the_drifted_sentence_info(caplog):
    # natural-speed video: one Latin word ("update", one timestamp for six letters) used to send the whole result to
    # sentence_info, whose text runs two chars ahead of its punctuation and timestamps after two VAD joins
    r = _latin_excerpt()
    with caplog.at_level("WARNING"):
        tr = transcript_from_funasr(r)
    assert caplog.text == ""
    assert tr.text == r["text"]                      # the punctuation model's own marks, where it put them
    assert "我给大家update一下，我本来这个视频想干啥，我们下周有一个考试，没错，" in tr.text
    assert tr.segments == [(0, len(tr.chars) - 1)]   # a comma does not end a sentence
    speech = [c for c in tr.chars if not is_punct(c.c)]
    by_index = {k: c for k, c in enumerate(speech)}
    assert by_index[5].c == "然" and by_index[5].start == 14.65
    at = tr.text.index("我本来")
    assert (tr.chars[at].c, tr.chars[at].start) == ("我", 16.35)      # the subtitle cue starts at 16.27 s
    at = tr.text.index("啥")
    assert (tr.chars[at].end, tr.chars[at + 1].c) == (18.13, "，")
    at = tr.text.index("又是")
    assert tr.chars[at].start == 20.91 and tr.chars[-1].c == "。" and tr.chars[-2].end == 23.05


def test_funasr_latin_word_letters_share_its_one_timestamp():
    r = _latin_excerpt()
    tr = transcript_from_funasr(r)
    a = tr.text.index("update")
    word_ts = r["timestamp"][5 + 6]                  # 这这个是哎 + 然后我给大家 → the seventh item of sentence two
    letters = tr.chars[a:a + 6]
    assert letters[0].start == word_ts[0] / 1000 and letters[-1].end == word_ts[1] / 1000
    assert all(x.end == y.start for x, y in zip(letters, letters[1:]))
    assert tr.chars[a + 6].c == "一" and tr.chars[a + 6].start == r["timestamp"][12][0] / 1000


def test_funasr_consecutive_latin_words_and_apostrophes_are_one_timestamp_each():
    r = {"text": "我说don't stop，好。", "timestamp": [[0, 100], [100, 200], [200, 600], [600, 900], [1000, 1200]]}
    tr = transcript_from_funasr(r)
    assert tr.text == r["text"]
    times = {i: (c.c, c.start, c.end) for i, c in enumerate(tr.chars)}
    assert times[2] == ("d", 0.2, 0.3) and times[6] == ("t", 0.5, 0.6)       # d o n t: four letters over 200-600
    assert times[5][0] == "'" and times[5][1] == times[5][2] == 0.5          # the apostrophe is zero-length
    assert times[8][0] == "s" and times[8][1] == 0.6 and times[11][2] == 0.9
    assert times[13] == ("好", 1.0, 1.2)


def test_funasr_unpunctuated_latin_words_are_cut_at_pauses_with_their_own_times():
    from shadow.config import SegmentationCfg
    # without the punctuation model FunASR's text is Paraformer's tokens joined by spaces
    text = "我 给 大 家 update 一 下 you know 我 本 来 想 干 啥"
    ts = [[i * 200, i * 200 + 180] for i in range(9)] + [[3000 + i * 200, 3180 + i * 200] for i in range(6)]
    tr = transcript_from_funasr({"text": text, "timestamp": ts}, pauses=SegmentationCfg())
    assert tr.text == "我给大家update一下youknow我本来想干啥"
    k = tr.text.index("我本来")
    assert tr.chars[k].start == 3.0 and tr.chars[k - 1].end == 1.78   # "know" ends where its timestamp ends
    assert [tr.text[a:b + 1] for a, b in tr.segments] == ["我给大家update一下youknow", "我本来想干啥"]


def test_funasr_top_level_count_mismatch_keeps_the_top_level_text_with_a_warning(caplog):
    r = {**_GLUED, "timestamp": _GLUED["timestamp"][:8]}
    with caplog.at_level("WARNING"):
        tr = transcript_from_funasr(r)
    assert "9 speech characters" in caplog.text and "8 timestamps" in caplog.text
    assert tr.text == _GLUED["text"] and tr.segments == [(0, 10)]       # not the drifted sentence_info
    speech = [c for c in tr.chars if not is_punct(c.c)]
    assert speech[0].start == 0.0 and speech[-1].end == 1.28
    assert all(x.start <= x.end <= y.start for x, y in zip(speech, speech[1:]))


def test_funasr_tokens_paraformer_does_not_time_are_zero_length():
    # sentence_postprocess gives "&" (AT&T, R&B) no timestamp: the units still pair exactly
    r = {"text": "我在AT&T上班。", "timestamp": [[0, 100], [100, 200], [200, 400], [450, 500], [500, 600], [600, 700]]}
    tr = transcript_from_funasr(r)
    c = {x.c + str(i): x for i, x in enumerate(tr.chars)}
    assert tr.text == "我在AT&T上班。"
    assert (c["A2"].start, c["T3"].end) == (0.2, 0.4)
    assert c["&4"].start == c["&4"].end == 0.4
    assert (c["T5"].start, c["T5"].end) == (0.45, 0.5) and c["上6"].start == 0.5


def test_funasr_last_resort_lays_units_proportionally_without_drift(caplog):
    # a stray "1@@" glues a digit to the next word: 4 units for 3 timestamps
    r = {"text": "我1hello好。", "timestamp": [[0, 300], [300, 900], [1200, 1500]]}
    with caplog.at_level("WARNING"):
        tr = transcript_from_funasr(r)
    assert "in 4 timed units for 3 timestamps" in caplog.text
    assert tr.text == "我1hello好。" and tr.segments == [(0, 8)]
    speech = [c for c in tr.chars if not is_punct(c.c)]
    assert speech[0].start == 0.0 and speech[-1].end == 1.5
    assert all(x.start <= x.end <= y.start for x, y in zip(speech, speech[1:]))


def test_funasr_per_character_count_coinciding_is_not_trusted_over_latin_words(caplog):
    # "ok" is one Paraformer token: 4 units, though the 5 timestamps equal the 5 speech characters
    r = {"text": "我说ok好", "timestamp": [[0, 100], [100, 200], [200, 300], [300, 400], [400, 500]]}
    with caplog.at_level("WARNING"):
        tr = transcript_from_funasr(r)
    assert "5 speech characters in 4 timed units for 5 timestamps" in caplog.text
    o, k = tr.chars[2], tr.chars[3]
    assert (o.start, o.end) != (0.2, 0.3) and o.end == k.start      # the word's letters share one span
    assert tr.chars[-1].end == 0.5


def test_funasr_ascii_sentence_end_after_a_latin_word_ends_a_sentence():
    r = {"text": "我说hello. 你好。", "timestamp": [[0, 100], [100, 200], [200, 400], [500, 600], [600, 700]]}
    assert transcript_from_funasr(r).segments == [(0, 8), (9, 11)]
    r = {"text": "我用v2.5版本ok? 好。", "timestamp": [[i * 100, i * 100 + 90] for i in range(9)]}
    tr = transcript_from_funasr(r)
    assert [tr.text[a:b + 1] for a, b in tr.segments] == ["我用v2.5版本ok? ", "好。"]   # a decimal point does not


def test_funasr_unpunctuated_apostrophe_word_still_cuts_at_pauses():
    from shadow.config import SegmentationCfg
    text = "我 说 don't stop 我 本 来 想"
    ts = [[0, 200], [200, 400], [400, 700], [700, 1000], [2000, 2200], [2200, 2400], [2400, 2600], [2600, 2800]]
    tr = transcript_from_funasr({"text": text, "timestamp": ts}, pauses=SegmentationCfg())
    assert tr.text == "我说don'tstop我本来想"
    assert [tr.text[a:b + 1] for a, b in tr.segments] == ["我说don'tstop", "我本来想"]


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


@pytest.mark.parametrize("punctuator", [None, "fake"])
def test_paraformer_never_loads_ct_punc(monkeypatch, punctuator):
    import sys
    import types
    from shadow.ingest.asr import ParaformerASR
    seen = {}

    class FakeAutoModel:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setitem(sys.modules, "funasr", types.SimpleNamespace(AutoModel=FakeAutoModel))
    ParaformerASR("m", "cpu", punctuator=None if punctuator is None else _Marks())._load()
    assert "punc_model" not in seen
    assert seen["model"] == "m" and seen["vad_model"] == "fsmn-vad"


class _Marks:
    """Fake punctuator: a full stop after every 4th speech char, and at the end."""
    def __init__(self):
        self.calls = []

    def punctuate(self, text):
        self.calls.append(text)
        sp = text.replace(" ", "")
        return "".join(ch + ("。" if (i + 1) % 4 == 0 or i == len(sp) - 1 else "") for i, ch in enumerate(sp))


class _Unpunctuated:
    def generate(self, **kw):
        ts = [[i * 100, i * 100 + 100] for i in range(8)]
        return [{"text": "我 是 学 生 我 爱 中 文", "timestamp": ts}]


def test_asr_run_punctuates_with_sherpa(tmp_path):
    from shadow.config import SegmentationCfg
    from shadow.ingest.asr import ParaformerASR
    marks = _Marks()
    asr = ParaformerASR("none", "cpu", punctuator=marks, segmentation=SegmentationCfg()); asr._model = _Unpunctuated()
    tr = asr.transcribe(tmp_path / "x.wav")
    assert tr.text == "我是学生。我爱中文。"
    assert len(tr.segments) == 2
    speech = [c for c in tr.chars if not is_punct(c.c)]
    assert [round(c.start, 1) for c in speech] == [i / 10 for i in range(8)]       # one timestamp per char
    assert marks.calls == ["我是学生我爱中文"]


def test_a_punctuator_that_adds_nothing_still_splits_at_pauses(tmp_path):
    from shadow.config import SegmentationCfg
    from shadow.ingest.asr import ParaformerASR

    class Nothing:
        def punctuate(self, text): return text
    ts = [[i * 100 + (900 if i >= 8 else 0), i * 100 + 100 + (900 if i >= 8 else 0)] for i in range(16)]

    class Gen:
        def generate(self, **kw): return [{"text": " ".join("我是学生我爱中文你好吗再见谢谢你"), "timestamp": ts}]
    asr = ParaformerASR("none", "cpu", punctuator=Nothing(), segmentation=SegmentationCfg()); asr._model = Gen()
    assert len(asr.transcribe(tmp_path / "x.wav").segments) == 2


def test_hear_skips_punctuation(tmp_path):
    from shadow.config import SegmentationCfg
    from shadow.ingest.asr import AsrHearer, ParaformerASR
    marks = _Marks()
    asr = ParaformerASR("none", "cpu", punctuator=marks, segmentation=SegmentationCfg()); asr._model = _Unpunctuated()
    assert AsrHearer(asr).hear(tmp_path / "x.wav") == "我是学生我爱中文"
    assert marks.calls == []


def _gapped_gen(order):
    ts = [[i * 100 + (900 if i >= 8 else 0), i * 100 + 100 + (900 if i >= 8 else 0)] for i in range(16)]

    class Gen:
        def generate(self, **kw):
            order.append("generate")
            return [{"text": " ".join("我是学生我爱中文你好吗再见谢谢你"), "timestamp": ts}]
    return Gen()


def test_a_punctuator_that_cannot_load_is_tried_before_generate_and_falls_back_to_pauses(tmp_path, caplog):
    from shadow.config import SegmentationCfg
    from shadow.ingest.asr import ParaformerASR
    order = []

    class NoLoad:
        def _load(self):
            order.append("load")
            raise OSError("no network")
        def punctuate(self, text): raise AssertionError("must not be called")
    asr = ParaformerASR("none", "cpu", punctuator=NoLoad(), segmentation=SegmentationCfg()); asr._model = _gapped_gen(order)
    with caplog.at_level("WARNING"):
        tr = asr.transcribe(tmp_path / "x.wav")
    assert order == ["load", "generate"]
    assert len(tr.segments) == 2
    assert any("punctuation model could not be loaded" in r.message for r in caplog.records)


def test_a_punctuator_that_raises_falls_back_to_pauses(tmp_path, caplog):
    from shadow.config import SegmentationCfg
    from shadow.ingest.asr import ParaformerASR

    class Boom:
        def punctuate(self, text): raise RuntimeError("boom")
    asr = ParaformerASR("none", "cpu", punctuator=Boom(), segmentation=SegmentationCfg()); asr._model = _gapped_gen([])
    with caplog.at_level("WARNING"):
        tr = asr.transcribe(tmp_path / "x.wav")
    assert len(tr.segments) == 2
    assert any("punctuation failed" in r.message for r in caplog.records)


def test_warm_also_warms_the_punctuator():
    from shadow.ingest.asr import ParaformerASR
    seen = []

    class P:
        def _load(self): seen.append("p")
    asr = ParaformerASR("none", "cpu", punctuator=P()); asr._model = object()
    asr.warm()
    assert seen == ["p"]

