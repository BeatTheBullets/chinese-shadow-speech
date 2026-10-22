from dataclasses import replace
import pytest
from shadow.ingest.splitcheck import SplitReport, gate_passes, match, piece_ends, reference_breaks, split_report
from shadow.ingest.text import is_punct
from shadow.ingest.transcript import TimedChar, Transcript, append_segment


def timed(text: str, t0: float = 0.0) -> list[TimedChar]:
    """One second per speech char; punctuation is zero-length at the previous end."""
    out, t = [], t0
    for ch in text:
        if is_punct(ch):
            out.append(TimedChar(ch, t, t))
        else:
            out.append(TimedChar(ch, t, t + 1.0))
            t += 1.0
    return out


def tr_of(*cues: str) -> Transcript:
    tr, t = Transcript(), 0.0
    for cue in cues:
        chars = timed(cue, t)
        append_segment(tr, chars)
        t = chars[-1].end
    return tr


def test_match_one_to_one_within_tolerance():
    assert match([1.0, 2.0, 5.0], [1.1, 5.5]) == (1, 2, 1)


def test_reference_breaks_from_cues_and_marks():
    all_, ends = reference_breaks(tr_of("我是学生，我很好", "你呢"))
    assert all_ == [4.0, 7.0]                    # after 生, after 好; the final cue end is dropped
    assert ends == [7.0]                         # no 。 in the file: the cue ends


def test_reference_ends_use_full_stops_when_present():
    all_, ends = reference_breaks(tr_of("我是学生。你呢？他好"))
    assert ends == [4.0, 6.0]                    # after 生 and after 呢
    assert all_ == [4.0, 6.0]


def test_split_report_counts_lengths_and_inside_word():
    text = "我是学生" + "好" * 31 + "中国人民" + "很好的人"
    chars = timed(text)
    n = len(chars)
    ranges = [(0, 3), (4, 34), (35, 35), (36, n - 1)]            # a 31-char piece, then a cut inside 中国
    rep = split_report(chars, ranges, [4.0], [4.0])
    assert (rep.pieces, rep.over_25, rep.over_30, rep.under_4) == (4, 1, 1, 1)
    assert rep.inside_word >= 1
    assert rep.recall == 1.0 and rep.precision == pytest.approx(1 / 3)
    assert piece_ends(chars, ranges) == [4.0, 35.0, 36.0]


def test_gate_passes_needs_recall_f1_and_no_piece_over_30():
    a = SplitReport(precision=.9, recall=.8, f1=.85, end_recall=.9, pieces=10, over_25=0, over_30=0, under_4=0, inside_word=0)
    assert gate_passes(a, replace(a, f1=.86, end_recall=.9))
    assert not gate_passes(a, replace(a, end_recall=.89))
    assert not gate_passes(a, replace(a, f1=.84))
    assert not gate_passes(a, replace(a, f1=.9, end_recall=.95, over_30=1))
