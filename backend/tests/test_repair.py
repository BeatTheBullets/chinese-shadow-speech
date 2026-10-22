from shadow.ingest.align import Span
from shadow.ingest.repair import MIN_SPAN_S, REPAIRED_CONF, coarse_times, repair_spans
from shadow.ingest.transcript import TimedChar


def _t(spans):
    return [(round(s.start, 3), round(s.end, 3), s.conf) for s in spans]


def test_coarse_times_match_speech_chars_and_skip_punctuation():
    chars = [TimedChar("我", 8.63, 8.87), TimedChar("，", 8.87, 8.87), TimedChar("好", 8.9, 9.1)]
    assert coarse_times("我，好。", chars) == [(8.63, 8.87), (8.9, 9.1)]


def test_coarse_times_line_up_edited_text_and_leave_added_chars_none():
    # the edited text has 学 where the ASR heard 雪 (a substitution keeps its time) and adds 啊 (no ASR char)
    chars = [TimedChar("我", 0.0, 0.2), TimedChar("雪", 0.2, 0.4), TimedChar("中", 0.4, 0.6), TimedChar("文", 0.6, 0.8)]
    assert coarse_times("我学中文啊", chars) == [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), None]


def test_zero_length_span_takes_the_coarse_span_with_conf_half():
    spans = [Span("我", 7.63, 7.63, 1.0), Span("好", 8.9, 9.1, 1.0)]
    assert _t(repair_spans(spans, [(8.63, 8.87), (8.9, 9.1)])) == [(8.63, 8.87, REPAIRED_CONF), (8.9, 9.1, 1.0)]


def test_span_starting_too_early_takes_the_coarse_span():
    # lesson 1, sentence 0: Qwen3 starts 我 a second early (7.63–8.59); the ASR has it at 8.63–8.87
    spans = [Span("我", 7.63, 8.59, 1.0), Span("今", 8.88, 9.1, 1.0)]
    assert _t(repair_spans(spans, [(8.63, 8.87), (8.87, 9.1)])) == [(8.63, 8.87, 0.5), (8.88, 9.1, 1.0)]


def test_small_drift_and_missing_coarse_keep_the_aligner_span():
    spans = [Span("我", 1.2, 1.4, 1.0), Span("好", 1.4, 1.6, 1.0)]
    assert repair_spans(spans, [(1.0, 1.3), None]) == spans          # 0.2 s drift is within 0.3 s


def test_repaired_spans_are_made_monotonic():
    # the coarse span of 我 ends after the aligner's start of 好
    spans = [Span("我", 0.0, 0.0, 1.0), Span("好", 0.3, 0.6, 1.0)]
    out = repair_spans(spans, [(0.2, 0.4), (0.35, 0.6)])
    assert _t(out) == [(0.2, 0.4, 0.5), (0.4, 0.6, 1.0)]
    for a, b in zip(out, out[1:]):
        assert a.start <= a.end <= b.start <= b.end


def test_without_coarse_times_zero_length_spans_share_the_gap_to_the_next_span():
    # Anki segments have no transcript: two zero-length chars before a span at 1.0 split 0.4–1.0 evenly
    spans = [Span("你", 0.1, 0.4, 1.0), Span("好", 0.4, 0.4, 1.0), Span("吗", 0.4, 0.4, 0.0), Span("呀", 1.0, 1.3, 1.0)]
    assert _t(repair_spans(spans)) == [(0.1, 0.4, 1.0), (0.4, 0.7, 0.5), (0.7, 1.0, 0.5), (1.0, 1.3, 1.0)]


def test_zero_length_last_span_without_a_next_one_gets_the_minimum_duration():
    spans = [Span("你", 0.1, 0.4, 1.0), Span("好", 0.4, 0.4, 1.0)]
    assert _t(repair_spans(spans)) == [(0.1, 0.4, 1.0), (0.4, 0.44, REPAIRED_CONF)]


def test_empty_spans_and_coarse_of_the_wrong_length_are_tolerated():
    assert repair_spans([], []) == []
    spans = [Span("你", 0.0, 0.0, 1.0), Span("好", 0.5, 0.8, 1.0)]
    # one coarse time for two spans: treated as no coarse times (gap fill only)
    assert _t(repair_spans(spans, [(9.0, 9.5)])) == [(0.0, 0.5, 0.5), (0.5, 0.8, 1.0)]


def test_repaired_span_squeezed_to_zero_by_the_previous_span_does_not_stay_zero_length():
    # 好's coarse span ends where 我 (aligner span) ends: after the monotonic pass it would be 0.5–0.5
    spans = [Span("我", 0.0, 0.5, 1.0), Span("好", 0.0, 0.0, 1.0), Span("吗", 0.8, 1.0, 1.0)]
    out = repair_spans(spans, [(0.0, 0.5), (0.3, 0.5), (0.8, 1.0)])
    assert _t(out) == [(0.0, 0.5, 1.0), (0.5, 0.8, 0.5), (0.8, 1.0, 1.0)]
    assert all(s.end > s.start for s in out)


def _check(out):
    assert all(s.end - s.start >= MIN_SPAN_S - 1e-9 for s in out)
    for a, b in zip(out, out[1:]):
        assert a.end <= b.start + 1e-9


def test_squeezed_trailing_span_gets_the_minimum_duration():
    spans = [Span("我", 0.0, 0.5, 1.0), Span("好", 0.0, 0.0, 1.0)]
    out = repair_spans(spans, [(0.0, 0.5), (0.3, 0.5)])
    assert _t(out) == [(0.0, 0.5, 1.0), (0.5, 0.54, REPAIRED_CONF)]
    _check(out)


def test_zero_length_run_followed_by_a_span_at_the_same_instant_pushes_it_forward():
    spans = [Span("你", 0.5, 0.5, 1.0), Span("好", 0.5, 0.9, 1.0)]
    out = repair_spans(spans)
    assert _t(out) == [(0.5, 0.54, REPAIRED_CONF), (0.54, 0.9, 1.0)]
    _check(out)


def test_pushing_a_span_forward_cascades_to_the_next_too_short_one():
    spans = [Span("你", 0.0, 0.0, 1.0), Span("好", 0.0, 0.05, 1.0), Span("吗", 0.05, 0.2, 1.0)]
    out = repair_spans(spans)
    assert _t(out) == [(0.0, 0.04, REPAIRED_CONF), (0.04, 0.08, 1.0), (0.08, 0.2, 1.0)]
    _check(out)


def test_wrong_length_coarse_is_logged(caplog):
    with caplog.at_level("WARNING"):
        repair_spans([Span("你", 0.0, 0.5, 1.0)], [(0.0, 0.1), (0.1, 0.2)])
    assert "coarse" in caplog.text


def test_clamp_spans_pulls_an_extended_last_span_back_inside_the_bounds():
    from shadow.ingest.repair import clamp_spans
    spans = [Span("a", 1.0, 1.5, 1.0), Span("b", 1.5, 2.0, 1.0), Span("c", 2.0, 2.04, 0.5)]
    out = clamp_spans(spans, 1.0, 2.0)
    assert [(s.start, s.end) for s in out] == [(1.0, 1.5), (1.5, 1.96), (1.96, 2.0)]
    assert clamp_spans(spans, 1.0, 2.04) == spans and clamp_spans([], 0.0, 1.0) == []
