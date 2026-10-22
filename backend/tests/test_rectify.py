from shadow.ingest.text import Cue
from shadow.ingest.transcript import transcript_from_cues
from shadow.ingest.rectify import make_chunks, split_chunk, rectify_transcript

TEXT = "我今天想跟你们聊一聊学中文的方法，其实方法有很多，但是最重要的是坚持。"


def tr_one():
    return transcript_from_cues([Cue(0.0, 10.0, TEXT)])


def test_chunks_cut_at_segment_boundaries():
    cues = [Cue(i, i + 1, "一二三四五六七八九十" * 10) for i in range(8)]   # 8 × 100 chars
    tr = transcript_from_cues(cues)
    chunks = make_chunks(tr, max_chars=250)
    assert [(c.start, c.end) for c in chunks] == [(0, 199), (200, 399), (400, 599), (600, 799)]


def test_split_chunk_splits_at_sentence_punct():
    tr = tr_one()
    res = split_chunk(tr, make_chunks(tr)[0])
    assert [s.text for s in res] == ["我今天想跟你们聊一聊学中文的方法，", "其实方法有很多，", "但是最重要的是坚持。"]
    assert [(s.char_from, s.char_to) for s in res] == [(0, 16), (17, 24), (25, 34)]


def test_rectify_transcript_covers_every_chunk_without_shifting():
    tr = transcript_from_cues([Cue(0.0, 10.0, TEXT), Cue(10.0, 20.0, TEXT)])   # two 35-char segments
    res = rectify_transcript(tr, max_chars=40)
    assert [(s.char_from, s.char_to) for s in res] == [(0, 16), (17, 24), (25, 34), (35, 51), (52, 59), (60, 69)]
    assert "".join(s.text for s in res) == TEXT * 2
