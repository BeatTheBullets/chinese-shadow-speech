import pytest

from shadow.ingest.asr import transcript_from_funasr, FakeASR
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
