import random
import pytest
from shadow.ingest.subalign import (
    MAX_SILENCE_S, MAX_STRETCH_EXTRA, MIN_ANCHOR_RUN, MIN_SUBTITLE_MATCH, align_text_to_asr,
)
from shadow.ingest.text import Cue, is_punct
from shadow.ingest.transcript import TimedChar, Transcript, transcript_from_cues

STEP = 0.25


def asr_of(text: str, start: float = 0.0, step: float = 0.5) -> Transcript:
    """An ASR transcript whose k-th speech char spans [start + k*step, start + (k+1)*step]."""
    speech = [c for c in text if not is_punct(c)]
    return transcript_from_cues([Cue(start, start + len(speech) * step, text)])


def asr_chars(*chars: tuple[str, float, float]) -> Transcript:
    return Transcript([TimedChar(*c) for c in chars], [(0, len(chars) - 1)])


def speech_times(tr: Transcript) -> list[tuple[str, float, float]]:
    return [(c.c, c.start, c.end) for c in tr.chars if not is_punct(c.c)]


def assert_monotonic(tr: Transcript):
    for a, b in zip(tr.chars, tr.chars[1:]):
        assert a.start <= a.end <= b.start <= b.end, (a, b)


def test_constants():
    assert (MIN_SUBTITLE_MATCH, MIN_ANCHOR_RUN, MAX_STRETCH_EXTRA, MAX_SILENCE_S) == (0.5, 3, 2, 2.0)


def test_identical_text_anchors_every_char_to_the_asr_times():
    asr = asr_of("大家好欢迎回来", start=2.0)
    a = align_text_to_asr(["大家好", "欢迎回来"], asr)
    assert a.transcript.text == "大家好欢迎回来" and a.transcript.segments == [(0, 2), (3, 6)]
    assert speech_times(a.transcript) == speech_times(asr)
    assert (a.matched, a.total, a.ratio) == (7, 7, 1.0)


def test_homophone_substitutions_between_trusted_runs_keep_subtitle_text_and_use_asr_times():
    asr = asr_of("我今天想跟你门聊一聊学中闻的方法")       # ASR heard 们 as 门 and 文 as 闻
    a = align_text_to_asr(["我今天想跟你们聊一聊学中文的方法"], asr)
    assert a.transcript.text == "我今天想跟你们聊一聊学中文的方法"
    assert [(c.start, c.end) for c in a.transcript.chars] == [(c.start, c.end) for c in asr.chars]
    assert (a.matched, a.total) == (14, 16)


def test_runs_shorter_than_three_are_not_trusted():
    a = align_text_to_asr(["你们好吗"], asr_of("你门好吗"))
    assert a.matched == 0 and a.ratio == 0.0


def test_subtitle_char_missing_from_asr_is_interpolated_between_its_neighbours():
    asr = asr_chars(("我", 0.0, 0.5), ("们", 0.5, 1.0), ("非", 1.0, 1.5),
                    ("喜", 2.5, 3.0), ("欢", 3.0, 3.5), ("你", 3.5, 4.0))
    a = align_text_to_asr(["我们非常喜欢你"], asr)        # 常 was not recognised
    assert speech_times(a.transcript)[3] == ("常", 1.5, 2.5)
    assert (a.matched, a.total) == (6, 7)


def test_several_missing_chars_share_the_gap_evenly():
    asr = asr_chars(("我", 0.0, 0.5), ("们", 0.5, 1.0), ("真", 1.0, 1.5),
                    ("喜", 3.0, 3.5), ("欢", 3.5, 4.0), ("你", 4.0, 4.5))
    a = align_text_to_asr(["我们真的非常喜欢你"], asr)
    assert [t[1:] for t in speech_times(a.transcript)[3:6]] == [(1.5, 2.0), (2.0, 2.5), (2.5, 3.0)]


def test_extra_asr_chars_are_ignored():
    asr = asr_of("嗯我们走吧嗯去学校")                   # fillers not in the subtitles
    a = align_text_to_asr(["我们走吧去学校"], asr)
    assert a.transcript.text == "我们走吧去学校"
    t = speech_times(asr)
    assert speech_times(a.transcript) == t[1:5] + t[6:]
    assert a.ratio == 1.0


def test_punctuation_is_zero_length_at_the_previous_chars_end():
    a = align_text_to_asr(["你好世界，今天很好。"], asr_of("你好世界今天很好"))
    comma, stop = a.transcript.chars[4], a.transcript.chars[9]
    assert (comma.c, comma.start, comma.end) == ("，", 2.0, 2.0)
    assert (stop.c, stop.start, stop.end) == ("。", 4.0, 4.0)


def test_leading_punctuation_sits_at_the_first_anchor():
    a = align_text_to_asr(["“你好吗”"], asr_of("你好吗", start=3.0))
    assert (a.transcript.chars[0].start, a.transcript.chars[0].end) == (3.0, 3.0)
    assert (a.transcript.chars[-1].start, a.transcript.chars[-1].end) == (4.5, 4.5)


def test_unanchored_leading_and_trailing_text_is_clamped_to_the_first_and_last_anchor():
    asr = asr_chars(("中", 3.0, 3.5), ("间", 3.5, 4.0), ("的", 4.0, 4.5))
    a = align_text_to_asr(["开头中间的结尾"], asr)
    assert speech_times(a.transcript) == [
        ("开", 3.0, 3.0), ("头", 3.0, 3.0), ("中", 3.0, 3.5), ("间", 3.5, 4.0), ("的", 4.0, 4.5),
        ("结", 4.5, 4.5), ("尾", 4.5, 4.5)]


def test_times_are_monotonic_even_when_asr_times_overlap():
    asr = asr_chars(("一", 0.0, 1.0), ("二", 0.8, 1.2), ("三", 1.1, 1.5), ("四", 1.4, 1.6), ("五", 1.5, 2.0))
    a = align_text_to_asr(["一二三", "六四五"], asr)
    assert_monotonic(a.transcript)
    assert a.transcript.chars[1].start == 1.0       # clamped to the previous char's end


def test_segments_are_one_per_piece_and_cover_punctuation():
    a = align_text_to_asr(["第一句。", "第二句，", "第三句！"], asr_of("第一句第二句第三句"))
    assert a.transcript.segments == [(0, 3), (4, 7), (8, 11)]
    assert_monotonic(a.transcript)


def test_empty_pieces_get_no_segment():
    a = align_text_to_asr(["", "你好吗"], asr_of("你好吗"))
    assert a.transcript.segments == [(0, 2)]


def test_unrelated_text_has_a_low_ratio():
    a = align_text_to_asr(["大家好欢迎回来"], asr_of("我今天想跟你们聊一聊学中文的方法"))
    assert a.ratio < MIN_SUBTITLE_MATCH
    assert a.transcript.text == "大家好欢迎回来"
    assert_monotonic(a.transcript)


# --- the ASR has speech the subtitles do not cover -------------------------------------------------------------

SUB = "我今天想跟你们聊一聊学中文但是最重要的是坚持了"        # 23 speech chars
EXTRA = "后来我们去了公园他也坚持说好了"                       # unsubtitled speech: shares chars, no trigram


def timed(text: str, start: float) -> list[TimedChar]:
    return [TimedChar(c, start + k * STEP, start + (k + 1) * STEP) for k, c in enumerate(text)]


def asr_from(*parts: str) -> tuple[Transcript, list[tuple[float, float]]]:
    """The ASR transcript of `parts` spoken back to back, and each part's (start, end)."""
    chars, spans, t = [], [], 0.0
    for p in parts:
        chars += timed(p, t)
        spans.append((t, t + len(p) * STEP))
        t += len(p) * STEP
    return Transcript(chars, [(0, len(chars) - 1)]), spans


def asr_at(*parts: tuple[str, float]) -> tuple[Transcript, list[tuple[float, float]]]:
    """The ASR transcript of each (text, start) part, and each part's (start, end)."""
    chars, spans = [], []
    for text, start in parts:
        chars += timed(text, start)
        spans.append((start, start + len(text) * STEP))
    return Transcript(chars, [(0, len(chars) - 1)]), spans


def piece_spans(tr: Transcript) -> list[tuple[float, float]]:
    """The (start, end) of each segment's chars: the coarse span its sentences are aligned around."""
    return [(min(c.start for c in tr.chars[a:b + 1]), max(c.end for c in tr.chars[a:b + 1])) for a, b in tr.segments]


def assert_inside(tr: Transcript, lo: float, hi: float):
    for c in tr.chars:
        assert lo <= c.start <= c.end <= hi, (c, lo, hi)


@pytest.mark.parametrize("sub, spoken", [
    pytest.param(SUB, SUB[:-1] + "啦", id="final_char_misheard"),
    pytest.param(SUB, SUB[:-1], id="final_char_dropped"),
    pytest.param(SUB[:-1], SUB[:-3] + "间池", id="last_two_misheard"),
])
def test_unrecognised_final_chars_stay_with_the_subtitled_speech(sub, spoken):
    asr, [(lo, hi), _] = asr_from(spoken, EXTRA)
    a = align_text_to_asr([sub], asr)
    assert_inside(a.transcript, lo, hi)
    assert a.ratio >= MIN_SUBTITLE_MATCH


def test_misheard_first_char_after_an_unsubtitled_intro_stays_with_the_subtitled_speech():
    asr, [_, (lo, hi)] = asr_from("我们先听一段音乐吧", "卧" + SUB[1:])
    a = align_text_to_asr([SUB], asr)
    assert_inside(a.transcript, lo, hi)


def test_nothing_is_placed_in_an_unsubtitled_passage_between_two_cues():
    first, second = "我今天想跟你们聊一聊学中文了", "但是最重要的是坚持"
    gap = "然后我们放了一段很长的音乐大家可以休息一下"           # 21 chars, about 5 s, contains 了
    asr, [_, (gap_start, gap_end), _] = asr_from(first[:-1] + "啦", gap, second)
    a = align_text_to_asr([first, second], asr)
    for c in a.transcript.chars:
        assert c.end <= gap_start or c.start >= gap_end, (c, gap_start, gap_end)
    assert_monotonic(a.transcript)


def _zipf_text(rng: random.Random, n: int) -> str:
    alphabet = [chr(0x4E00 + k) for k in range(400)]
    return "".join(rng.choices(alphabet, weights=[1 / (r + 1) for r in range(400)], k=n))


def test_unrelated_subtitles_against_a_much_longer_asr_do_not_match():
    rng = random.Random(7)
    sub, asr_text = _zipf_text(rng, 100), _zipf_text(rng, 3000)
    a = align_text_to_asr([sub], asr_from(asr_text)[0])
    assert a.ratio < MIN_SUBTITLE_MATCH


def test_true_subtitles_with_asr_errors_inside_much_more_speech_match_and_stay_in_place():
    rng = random.Random(11)
    sub = _zipf_text(rng, 300)
    misheard = "".join(rng.choice("乙丙丁") if rng.random() < 0.1 else c for c in sub)   # ~10 % substitutions
    asr, [_, (lo, hi), _] = asr_from(_zipf_text(rng, 500), misheard, _zipf_text(rng, 500))
    a = align_text_to_asr([sub[i:i + 15] for i in range(0, 300, 15)], asr)
    assert a.ratio >= 0.8
    assert_inside(a.transcript, lo, hi)


# --- cue boundaries and silences ------------------------------------------------------------------------------

FIRST, SECOND = "我今天想跟你们聊一聊学中文了", "但是最重要的是坚持"


def assert_spans_within(tr: Transcript, speech: list[tuple[float, float]]):
    for (a, b), (lo, hi) in zip(piece_spans(tr), speech, strict=True):
        assert lo <= a <= b <= hi, ((a, b), (lo, hi))


def assert_outside(tr: Transcript, gap_start: float, gap_end: float):
    for c in tr.chars:
        assert c.end <= gap_start or c.start >= gap_end, (c, gap_start, gap_end)


def test_a_run_does_not_extend_across_a_cue_boundary_into_unsubtitled_speech():
    # FIRST's final 了 is dropped; the unsubtitled passage ends with 了 right before SECOND
    gap = "然后我们放一段很长的音乐大家可以休息一下了"
    asr, [first, (g0, g1), second] = asr_from(FIRST[:-1], gap, SECOND)
    a = align_text_to_asr([FIRST, SECOND], asr)
    assert_outside(a.transcript, g0, g1)
    assert_spans_within(a.transcript, [first, second])


def test_a_run_does_not_extend_backwards_across_a_cue_boundary_into_unsubtitled_speech():
    # SECOND's first 但 is misheard as 担; the unsubtitled passage starts with 但 right after FIRST
    gap = "但然后我们放一段很长的音乐大家可以休息一下"
    asr, [first, (g0, g1), second] = asr_from(FIRST, gap, "担" + SECOND[1:])
    a = align_text_to_asr([FIRST, SECOND], asr)
    assert_outside(a.transcript, g0, g1)
    assert_spans_within(a.transcript, [first, second])


@pytest.mark.parametrize("noise", ["", "嗯"], ids=["nothing_heard", "one_char_heard_in_the_music"])
def test_a_dropped_edge_char_is_not_spread_over_a_silence_between_cues(noise):
    parts = [(FIRST[:-1], 0.0)] + ([(noise, 39.5)] if noise else []) + [(SECOND, 40.0)]
    asr, spans = asr_at(*parts)
    a = align_text_to_asr([FIRST, SECOND], asr)
    assert_outside(a.transcript, spans[0][1], 40.0)
    assert_spans_within(a.transcript, [spans[0], spans[-1]])


def test_a_dropped_char_is_not_spread_over_a_long_silence_inside_one_cue():
    asr, [(_, g0), (g1, _)] = asr_at(("我今天想跟你们", 0.0), ("一聊学中文", 30.0))   # the first 聊 is dropped
    a = align_text_to_asr(["我今天想跟你们聊一聊学中文"], asr)
    assert_outside(a.transcript, g0, g1)
    assert_monotonic(a.transcript)
