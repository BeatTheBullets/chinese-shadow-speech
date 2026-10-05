import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest

from shadow.ingest.text import Cue
from shadow.ingest.transcript import transcript_from_cues
from shadow.ingest import llm as llm_mod
from shadow.ingest.llm import RectifyOutput, RectSentence, FakeLLM, AnthropicLLM
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
        sent(0, 16, "我今天想跟你们聊一聊学中文的方法，"),
        sent(17, 24, "其实方法有很多，"),
        sent(25, 34, "但是最重要的是坚持。"),
    ])
    res = validate(out, chunk, tr)
    assert res is not None and [(s.char_from, s.char_to) for s in res] == [(0, 16), (17, 24), (25, 34)]


def test_validate_simplifies_llm_text_before_comparing():
    tr = tr_one()
    chunk = make_chunks(tr)[0]
    out = RectifyOutput(sentences=[
        sent(0, 16, "我今天想跟你們聊一聊學中文的方法，"),     # traditional 們 / 學
        sent(17, 34, "其實方法有很多，但是最重要的是堅持。"),
    ])
    res = validate(out, chunk, tr)
    assert res is not None
    assert [s.text for s in res] == ["我今天想跟你们聊一聊学中文的方法，", "其实方法有很多，但是最重要的是坚持。"]


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
    assert [(s.char_from, s.char_to) for s in res] == [(0, 16), (17, 24), (25, 34)]


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


def test_rectify_transcript_exception_falls_back_and_logs_warning(caplog):
    tr = tr_one()

    def boom(chunk_chars, context_chars):
        raise RuntimeError("401 invalid api key")
    with caplog.at_level(logging.WARNING, logger="shadow.ingest.rectify"):
        res = rectify_transcript(tr, FakeLLM(boom, lambda xs: xs))
    assert [(s.char_from, s.char_to) for s in res] == [(0, 16), (17, 24), (25, 34)]
    [rec] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "chunk 1/1" in rec.getMessage() and rec.exc_info and "401 invalid api key" in str(rec.exc_info[1])


def test_rectify_transcript_logs_validator_rejection_with_reason(caplog):
    tr = tr_one()
    with caplog.at_level(logging.WARNING, logger="shadow.ingest.rectify"):
        rectify_transcript(tr, FakeLLM(lambda c, x: RectifyOutput(sentences=[]), lambda xs: xs))
    [rec] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "chunk 1/1" in rec.getMessage() and "rejected" in rec.getMessage() and "no sentences" in rec.getMessage()


def test_rectify_transcript_multi_chunk_bad_chunk_falls_back_without_shifting():
    tr = transcript_from_cues([Cue(0.0, 10.0, TEXT), Cue(10.0, 20.0, TEXT)])   # two 35-char segments
    seen = []

    def fake(chunk_chars, context_chars):
        seen.append(("".join(chunk_chars), "".join(context_chars)))
        if len(seen) == 1:      # valid, and different from the fallback split (2 sentences, not 3)
            return RectifyOutput(sentences=[sent(0, 16, TEXT[:17]), sent(17, 34, TEXT[17:])])
        # chunk 2: off by one at the boundary, the first range starts in the context prefix
        return RectifyOutput(sentences=[sent(-1, 16, TEXT[34:35] + TEXT[:17]), sent(17, 34, TEXT[17:])])

    res = rectify_transcript(tr, FakeLLM(fake, lambda xs: xs), max_chars=40, context=10)

    assert [(c, x) for c, x in seen] == [(TEXT, ""), (TEXT, TEXT[25:35])]    # chunk 2 got its context prefix
    assert [(s.char_from, s.char_to, s.text) for s in res[:2]] == [(0, 16, TEXT[:17]), (17, 34, TEXT[17:])]
    chunk2 = res[2:]
    assert [(s.char_from, s.char_to) for s in chunk2] == [(35, 51), (52, 59), (60, 69)]
    assert "".join(s.text for s in chunk2) == TEXT


class _StubClient:
    """Stands in for anthropic.Anthropic(): records calls, returns queued JSON strings."""
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self.replies.pop(0))])


def make_anthropic(monkeypatch, tmp_path, replies):
    stub = _StubClient(replies)
    import anthropic
    monkeypatch.setattr(anthropic, "Anthropic", lambda: stub)
    return AnthropicLLM("claude-sonnet-5-5", "low", tmp_path), stub


GOOD = json.dumps({"sentences": [{"from": 0, "to": 1, "text": "你好"}]}, ensure_ascii=False)


def test_anthropic_rectify_caches_valid_response_and_never_sends_temperature(monkeypatch, tmp_path):
    llm, stub = make_anthropic(monkeypatch, tmp_path, [GOOD])
    assert llm.rectify(["你", "好"], []).sentences[0].text == "你好"
    assert llm.rectify(["你", "好"], []).sentences[0].text == "你好"
    assert len(stub.calls) == 1 and "temperature" not in stub.calls[0]
    assert len(list(tmp_path.glob("*.json"))) == 1 and not list(tmp_path.glob("*.tmp"))


def test_anthropic_rectify_corrupt_cache_file_is_a_miss_and_is_overwritten(monkeypatch, tmp_path):
    llm, stub = make_anthropic(monkeypatch, tmp_path, [GOOD, GOOD, GOOD])
    llm.rectify(["你", "好"], [])
    [cache_file] = tmp_path.glob("*.json")
    cache_file.write_text('{"sentences": [{"from": 0, "to"')           # truncated JSON
    assert llm.rectify(["你", "好"], []).sentences[0].text == "你好"
    assert len(stub.calls) == 2
    assert json.loads(cache_file.read_text())["sentences"][0]["text"] == "你好"
    cache_file.write_text('{"sentences": [{"nope": 1}]}')              # valid JSON, wrong schema
    llm.rectify(["你", "好"], [])
    assert len(stub.calls) == 3 and RectifyOutput.model_validate_json(cache_file.read_text())


def test_anthropic_rectify_schema_invalid_response_is_not_cached(monkeypatch, tmp_path):
    llm, stub = make_anthropic(monkeypatch, tmp_path, ['{"sentences": [{"from": 0}]}', GOOD])
    with pytest.raises(Exception):
        llm.rectify(["你", "好"], [])
    assert not list(tmp_path.iterdir())
    assert llm.rectify(["你", "好"], []).sentences[0].text == "你好"   # the retry reaches the API again
    assert len(stub.calls) == 2


def test_anthropic_translate_caches_only_matching_count(monkeypatch, tmp_path):
    llm, stub = make_anthropic(monkeypatch, tmp_path, ['{"translations": ["Hi"]}', '{"translations": ["Hi", "Bye"]}'])
    assert llm.translate(["你好", "再见"]) == ["", ""]
    assert not list(tmp_path.iterdir())
    assert llm.translate(["你好", "再见"]) == ["Hi", "Bye"]
    assert llm.translate(["你好", "再见"]) == ["Hi", "Bye"]
    assert len(stub.calls) == 2


def test_anthropic_cache_key_includes_prompt_version(monkeypatch, tmp_path):
    llm, stub = make_anthropic(monkeypatch, tmp_path, [GOOD, GOOD])
    llm.rectify(["你", "好"], [])
    monkeypatch.setattr(llm_mod, "PROMPT_VERSION", "2")
    llm.rectify(["你", "好"], [])
    assert len(stub.calls) == 2 and len(list(tmp_path.glob("*.json"))) == 2
