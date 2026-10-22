from __future__ import annotations
from dataclasses import dataclass
from shadow.ingest.text import is_punct, strip_punct
from shadow.ingest.transcript import Transcript

SENTENCE_END = set("。！？；")
CLAUSE_END = set("，、：")


@dataclass
class Chunk:
    start: int            # absolute, inclusive
    end: int              # absolute, inclusive


@dataclass
class RectSentenceOut:
    char_from: int
    char_to: int
    text: str


def make_chunks(tr: Transcript, max_chars: int = 600) -> list[Chunk]:
    chunks: list[Chunk] = []
    if not tr.chars:
        return chunks
    cur_start = 0
    for i, (a, b) in enumerate(tr.segments):
        is_last = i == len(tr.segments) - 1
        next_len = tr.segments[i + 1][1] - cur_start + 1 if not is_last else None
        if is_last or next_len > max_chars:
            chunks.append(Chunk(cur_start, b))
            cur_start = b + 1
    return chunks


def split_chunk(tr: Transcript, chunk: Chunk) -> list[RectSentenceOut]:
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


def rectify_transcript(tr: Transcript, max_chars: int = 600) -> list[RectSentenceOut]:
    """Sentences covering `tr`, split at punctuation and segment ends, chunk by chunk."""
    sentences: list[RectSentenceOut] = []
    for chunk in make_chunks(tr, max_chars):
        sentences.extend(split_chunk(tr, chunk))
    return sentences
