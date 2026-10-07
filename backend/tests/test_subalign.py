import pytest
from shadow.ingest.subalign import MIN_SUBTITLE_MATCH, align_text_to_asr
from shadow.ingest.text import Cue, is_punct
from shadow.ingest.transcript import TimedChar, Transcript, transcript_from_cues


def asr_of(text: str, start: float = 0.0, step: float = 0.5) -> Transcript:
    """An ASR transcript whose k-th speech char spans [start + k*step, start + (k+1)*step]."""
    speech = [c for c in text if not is_punct(c)]
    return transcript_from_cues([Cue(start, start + len(speech) * step, text)])


def speech_times(tr: Transcript) -> list[tuple[str, float, float]]:
    return [(c.c, c.start, c.end) for c in tr.chars if not is_punct(c.c)]


def assert_monotonic(tr: Transcript):
    for a, b in zip(tr.chars, tr.chars[1:]):
        assert a.start <= a.end <= b.start <= b.end, (a, b)


def test_min_subtitle_match_is_one_half():
    assert MIN_SUBTITLE_MATCH == 0.5


def test_identical_text_anchors_every_char_to_the_asr_times():
    asr = asr_of("大家好欢迎回来", start=2.0)
    tr, ratio = align_text_to_asr(["大家好", "欢迎回来"], asr)
    assert tr.text == "大家好欢迎回来" and tr.segments == [(0, 2), (3, 6)]
    assert speech_times(tr) == speech_times(asr)
    assert ratio == 1.0


def test_homophone_substitutions_keep_subtitle_text_and_use_asr_times():
    asr = asr_of("你门好吗")                    # ASR heard 们 as 门
    tr, ratio = align_text_to_asr(["你们好吗"], asr)
    assert tr.text == "你们好吗"
    assert [(c.start, c.end) for c in tr.chars] == [(c.start, c.end) for c in asr.chars]
    assert ratio == 0.75


def test_subtitle_char_missing_from_asr_is_interpolated_between_its_neighbours():
    asr = Transcript([TimedChar("我", 0.0, 0.5), TimedChar("好", 2.0, 2.5)], [(0, 1)])
    tr, ratio = align_text_to_asr(["我很好"], asr)       # 很 was not recognised
    assert [(c.c, c.start, c.end) for c in tr.chars] == [("我", 0.0, 0.5), ("很", 0.5, 2.0), ("好", 2.0, 2.5)]
    assert ratio == pytest.approx(2 / 3)


def test_several_missing_chars_share_the_gap_evenly():
    asr = Transcript([TimedChar("我", 0.0, 1.0), TimedChar("好", 4.0, 5.0)], [(0, 1)])
    tr, _ = align_text_to_asr(["我非常好"], asr)
    assert [(c.start, c.end) for c in tr.chars] == [(0.0, 1.0), (1.0, 2.5), (2.5, 4.0), (4.0, 5.0)]


def test_extra_asr_chars_are_ignored():
    asr = asr_of("嗯我们走吧")                   # filler 嗯 is not in the subtitles
    tr, ratio = align_text_to_asr(["我们走吧"], asr)
    assert tr.text == "我们走吧"
    assert speech_times(tr) == speech_times(asr)[1:]
    assert ratio == 1.0


def test_punctuation_is_zero_length_at_the_previous_chars_end():
    asr = asr_of("你好世界")
    tr, _ = align_text_to_asr(["你好，世界。"], asr)
    comma, stop = tr.chars[2], tr.chars[5]
    assert (comma.c, comma.start, comma.end) == ("，", 1.0, 1.0)
    assert (stop.c, stop.start, stop.end) == ("。", 2.0, 2.0)


def test_leading_punctuation_sits_at_the_first_anchor():
    asr = asr_of("你好", start=3.0)
    tr, _ = align_text_to_asr(["“你好”"], asr)
    assert (tr.chars[0].start, tr.chars[0].end) == (3.0, 3.0)
    assert (tr.chars[-1].start, tr.chars[-1].end) == (4.0, 4.0)


def test_unanchored_leading_and_trailing_text_is_clamped_to_the_first_and_last_anchor():
    asr = Transcript([TimedChar("中", 3.0, 3.5), TimedChar("间", 3.5, 4.0)], [(0, 1)])
    tr, _ = align_text_to_asr(["开头中间结尾"], asr)
    assert [(c.c, c.start, c.end) for c in tr.chars] == [
        ("开", 3.0, 3.0), ("头", 3.0, 3.0), ("中", 3.0, 3.5), ("间", 3.5, 4.0), ("结", 4.0, 4.0), ("尾", 4.0, 4.0)]


def test_times_are_monotonic_even_when_asr_times_overlap():
    asr = Transcript([TimedChar("一", 0.0, 1.0), TimedChar("二", 0.8, 1.2), TimedChar("三", 1.1, 1.5)], [(0, 2)])
    tr, _ = align_text_to_asr(["一二", "四三"], asr)
    assert_monotonic(tr)
    assert tr.chars[1].start == 1.0       # clamped to the previous char's end


def test_segments_are_one_per_piece_and_cover_punctuation():
    asr = asr_of("第一句第二句第三句")
    tr, _ = align_text_to_asr(["第一句。", "第二句，", "第三句！"], asr)
    assert tr.segments == [(0, 3), (4, 7), (8, 11)]
    assert_monotonic(tr)


def test_empty_pieces_get_no_segment():
    asr = asr_of("你好")
    tr, _ = align_text_to_asr(["", "你好"], asr)
    assert tr.segments == [(0, 1)]


def test_ratio_counts_only_chars_equal_to_their_asr_char():
    asr = asr_of("我今天想跟你们聊一聊学中文的方法")
    tr, ratio = align_text_to_asr(["大家好欢迎回来"], asr)
    assert ratio < MIN_SUBTITLE_MATCH
    assert tr.text == "大家好欢迎回来"
    assert_monotonic(tr)
