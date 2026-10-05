import json
from pathlib import Path

import pytest

from shadow.ingest.text import Cue
from shadow.ingest.transcript import transcript_from_cues
from shadow.ingest.llm import RectifyOutput, RectSentence, FakeLLM
from shadow.ingest.rectify import make_chunks, validate, fallback_sentences, rectify_transcript, Chunk

TEXT = "我今天想跟你们聊一聊学中文的方法，其实方法有很多，但是最重要的是坚持。"


def tr_one():
    return transcript_from_cues([Cue(0.0, 10.0, TEXT)])


def sent(frm: int, to: int, text: str) -> RectSentence:
    return RectSentence(**{"from": frm, "to": to, "text": text})


def test_chunks_cut_at_segment_boundaries_and_carry_context():
    cues = [Cue(i, i + 1, "一二三四五六七八九十" * 10) for i in range(8)]   # 8 × 100 chars
    tr = transcript_from_cues(cues)
    chunks = make_chunks(tr, max_chars=250, context=60)
    assert [(c.start, c.end) for c in chunks] == [(0, 199), (200, 399), (400, 599), (600, 799)]
    assert chunks[0].context_start == 0 and chunks[1].context_start == 140


def test_validate_accepts_good_output():
    tr = tr_one()
    chunk = make_chunks(tr)[0]
    out = RectifyOutput(sentences=[
        sent(0, 15, "我今天想跟你们聊一聊学中文的方法，"),
        sent(16, 23, "其实方法有很多，"),
        sent(24, 34, "但是最重要的是坚持。"),
    ])
    res = validate(out, chunk, tr)
    assert res is not None and [(s.char_from, s.char_to) for s in res] == [(0, 15), (16, 23), (24, 34)]


# The chunk covers absolute 10..34 (25 chars) with 10 chars of context before it. The LLM's
# from/to are chunk-relative, so the valid range is 0..24. Every case below is wrong in exactly
# one way, so each is rejected by its own check.
CHUNK_START = 10


def rel(a: int, b: int) -> RectSentence:
    """A sentence over chunk-relative a..b whose text is the raw text of those chars."""
    return sent(a, b, TEXT[CHUNK_START + a:CHUNK_START + b + 1])


def test_validate_translates_chunk_relative_indices_to_absolute():
    tr = tr_one()
    chunk = Chunk(start=CHUNK_START, end=34, context_start=0)
    res = validate(RectifyOutput(sentences=[rel(0, 9), rel(10, 24)]), chunk, tr)
    assert res is not None and [(s.char_from, s.char_to) for s in res] == [(10, 19), (20, 34)]


@pytest.mark.parametrize("sentences", [
    pytest.param([rel(0, 9), rel(11, 24)], id="gap"),
    pytest.param([rel(0, 10), rel(10, 24)], id="overlap"),
    pytest.param([rel(-1, 24)], id="starts_in_context_prefix"),
    pytest.param([rel(0, 25)], id="runs_past_chunk_end"),
    pytest.param([rel(0, 9), rel(10, 23)], id="stops_short_of_chunk_end"),
    pytest.param([sent(0, 24, "完全不一样的句子完全不一样的句子完全不一样")], id="text_differs_from_raw"),
    pytest.param([sent(0, 0, "学"), rel(1, 24)], id="text_too_short"),
    pytest.param([sent(0, -1, "。。"), rel(0, 24)], id="to_before_from"),
])
def test_validate_rejects_gap_overlap_bad_text_and_context_overlap(sentences):
    tr = tr_one()
    chunk = Chunk(start=CHUNK_START, end=34, context_start=0)
    assert validate(RectifyOutput(sentences=sentences), chunk, tr) is None


def test_validate_rejects_text_longer_than_60_chars():
    tr = transcript_from_cues([Cue(0.0, 20.0, TEXT * 2)])   # 70 chars, so an exact copy is still too long
    chunk = make_chunks(tr)[0]
    assert (chunk.start, chunk.end) == (0, 69)
    assert validate(RectifyOutput(sentences=[sent(0, 69, TEXT * 2)]), chunk, tr) is None


def test_fallback_splits_at_sentence_punct():
    tr = tr_one()
    res = fallback_sentences(tr, make_chunks(tr)[0])
    assert [s.text for s in res] == ["我今天想跟你们聊一聊学中文的方法，", "其实方法有很多，", "但是最重要的是坚持。"]


def test_rectify_transcript_uses_llm_then_falls_back_per_chunk():
    tr = tr_one()
    calls = []

    def bad(chunk_chars, context_chars):
        calls.append(len(chunk_chars))
        return RectifyOutput(sentences=[])
    res = rectify_transcript(tr, FakeLLM(bad, lambda xs: xs))
    assert calls == [35] and len(res) == 3


def test_recorded_response_fixture_validates():
    tr = tr_one()
    data = json.loads(Path(__file__).parents[1].joinpath("fixtures/rectify_response_1.json").read_text())
    out = RectifyOutput.model_validate(data)
    assert validate(out, make_chunks(tr)[0], tr) is not None
