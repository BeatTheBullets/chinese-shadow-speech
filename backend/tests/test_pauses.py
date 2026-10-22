import random

import jieba

from shadow.config import SegmentationCfg
from shadow.ingest.asr import transcript_from_funasr
from shadow.ingest.pauses import pause_ranges
from shadow.ingest.transcript import TimedChar

jieba.setLogLevel(60)
CFG = SegmentationCfg()


def chars(spec):
    """spec: (text, gap_after) pairs; 0.24 s per character, the gap after the last char of each text."""
    out, t = [], 0.0
    for text, gap in spec:
        for k, c in enumerate(text):
            out.append(TimedChar(c, t, t + 0.24))
            t += 0.24 + (gap if k == len(text) - 1 else 0.0)
    return out


def test_cuts_at_long_gaps():
    assert pause_ranges(chars([("我是学生", 0.6), ("我是中国人", 0)]), CFG) == [(0, 3), (4, 8)]


def test_never_cuts_inside_a_word():
    # 0.7 s gap between 中 and 国 of 中国: no cut there
    cs = chars([("我是学生我是中", 0.7), ("国人", 0)])
    assert pause_ranges(cs, CFG) == [(0, 8)]


def test_long_piece_split_at_largest_gap():
    text = "天地玄黄宇宙洪荒日月盈昃辰宿列张寒来暑往秋收冬藏闰余成岁"[:28]
    cs = chars([(text[:12], 0.3), (text[12:20], 0.27), (text[20:], 0)])
    assert pause_ranges(cs, CFG) == [(0, 11), (12, 27)]


def test_no_gaps_still_splits_long_text_at_word_boundaries():
    text = "我今天早上去了学校然后和同学一起吃午饭下午又回到教室认真地学习数学和英语"[:40]
    r = pause_ranges(chars([(text, 0.0)]), CFG)
    assert len(r) >= 2 and all(b - a + 1 <= 25 for a, b in r)
    ends, n = set(), 0
    for w in jieba.cut(text):
        n += len(w)
        ends.add(n - 1)
    assert all(b in ends for _, b in r)


def test_short_piece_merges_across_smaller_gap():
    cs = chars([("好", 0.6), ("我是学生", 0.9), ("我是中国人", 0)])
    assert pause_ranges(cs, CFG) == [(0, 4), (5, 9)]


def test_short_transcript_is_one_piece():
    assert pause_ranges(chars([("好", 0)]), CFG) == [(0, 0)]
    assert pause_ranges(chars([("你好", 0)]), CFG) == [(0, 1)]


def test_ranges_cover_every_char_once():
    rng = random.Random(7)
    pool = "我你他是的了在有和人这中大为上个国不来到时要就出会可也对生能而子那得于着下自之年过发后作里用道行所然家种事成方多经"
    cs, t = [], 0.0
    for _ in range(200):
        cs.append(TimedChar(rng.choice(pool), t, t + 0.24))
        t += 0.24 + rng.choice([0.0, 0.05, 0.3, 0.7, 1.2])
    r = pause_ranges(cs, CFG)
    assert [i for a, b in r for i in range(a, b + 1)] == list(range(200))
    assert all(a <= b for a, b in r)


def _ts(n, gaps):
    out, t = [], 0
    for k in range(n):
        out.append([t, t + 240])
        t += 240 + gaps.get(k, 0)
    return out


def test_unpunctuated_funasr_result_segments_by_pauses():
    text = "我是学生我是中国人"
    res = {"text": " ".join(text), "timestamp": _ts(9, {3: 600})}
    tr = transcript_from_funasr(res, pauses=CFG)
    assert tr.text == text
    assert tr.segments == [(0, 3), (4, 8)]


def test_punctuated_result_ignores_pauses():
    res = {"text": "你好，世界。再见。", "timestamp": _ts(6, {1: 900, 3: 900})}
    tr = transcript_from_funasr(res, pauses=CFG)
    assert tr.segments == [(0, 5), (6, 8)]
