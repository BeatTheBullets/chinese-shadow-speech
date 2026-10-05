from __future__ import annotations
from dataclasses import dataclass
from rapidfuzz.distance import Levenshtein
from shadow.ingest.llm import LLM, RectifyOutput
from shadow.ingest.text import is_punct, strip_punct
from shadow.ingest.transcript import Transcript

SENTENCE_END = set("。！？；")
CLAUSE_END = set("，、：")


@dataclass
class Chunk:
    start: int            # absolute, inclusive
    end: int              # absolute, inclusive
    context_start: int    # absolute index where context-only prefix begins


@dataclass
class RectSentenceOut:
    char_from: int
    char_to: int
    text: str


def make_chunks(tr: Transcript, max_chars: int = 600, context: int = 60) -> list[Chunk]:
    chunks: list[Chunk] = []
    if not tr.chars:
        return chunks
    cur_start = 0
    for i, (a, b) in enumerate(tr.segments):
        is_last = i == len(tr.segments) - 1
        next_len = tr.segments[i + 1][1] - cur_start + 1 if not is_last else None
        if is_last or next_len > max_chars:
            chunks.append(Chunk(cur_start, b, max(0, cur_start - context)))
            cur_start = b + 1
    return chunks


def validate(out: RectifyOutput, chunk: Chunk, tr: Transcript) -> list[RectSentenceOut] | None:
    sents = sorted(out.sentences, key=lambda s: s.from_)
    if not sents:
        return None
    expected = chunk.start
    result: list[RectSentenceOut] = []
    for s in sents:
        a, b = chunk.start + s.from_, chunk.start + s.to
        if a != expected or b < a or b > chunk.end:
            return None
        raw = "".join(c.c for c in tr.chars[a:b + 1])
        raw_speech, text_speech = strip_punct(raw), strip_punct(s.text)
        if not (2 <= len(s.text) <= 60):
            return None
        if Levenshtein.distance(text_speech, raw_speech) / max(len(raw_speech), 1) >= 0.25:
            return None
        result.append(RectSentenceOut(a, b, s.text))
        expected = b + 1
    if expected != chunk.end + 1:
        return None
    return result


def fallback_sentences(tr: Transcript, chunk: Chunk) -> list[RectSentenceOut]:
    out: list[RectSentenceOut] = []
    a = chunk.start
    seg_ends = {b for _, b in tr.segments}
    for i in range(chunk.start, chunk.end + 1):
        ch = tr.chars[i].c
        nxt = tr.chars[i + 1].c if i + 1 <= chunk.end else ""
        at_end = (ch in SENTENCE_END or ch in CLAUSE_END or i in seg_ends or i == chunk.end) and not is_punct(nxt)
        if at_end:
            text = "".join(c.c for c in tr.chars[a:i + 1])
            if strip_punct(text):
                out.append(RectSentenceOut(a, i, text))
            a = i + 1
    return out


def rectify_transcript(tr: Transcript, llm: LLM | None, enabled: bool = True,
                       max_chars: int = 600, context: int = 60) -> list[RectSentenceOut]:
    sentences: list[RectSentenceOut] = []
    for chunk in make_chunks(tr, max_chars, context):
        validated = None
        if enabled and llm is not None:
            try:
                chunk_chars = [c.c for c in tr.chars[chunk.start:chunk.end + 1]]
                ctx = [c.c for c in tr.chars[chunk.context_start:chunk.start]]
                validated = validate(llm.rectify(chunk_chars, ctx), chunk, tr)
            except Exception:
                validated = None
        sentences.extend(validated if validated is not None else fallback_sentences(tr, chunk))
    return sentences
