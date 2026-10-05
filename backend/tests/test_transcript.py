from shadow.ingest.text import Cue
from shadow.ingest.transcript import transcript_from_cues, Transcript


def test_interpolates_times_per_char():
    tr = transcript_from_cues([Cue(1.0, 2.0, "你好。")])
    assert tr.text == "你好。"
    assert tr.chars[0].start == 1.0 and abs(tr.chars[1].end - 2.0) < 1e-6
    assert tr.chars[2].start == tr.chars[2].end == tr.chars[1].end   # punctuation zero-length
    assert tr.segments == [(0, 2)]


def test_overlapping_and_unordered_cues_stay_monotonic():
    tr = transcript_from_cues([Cue(3.0, 4.0, "后面"), Cue(1.0, 3.5, "前面")])
    times = [c.start for c in tr.chars] + [tr.chars[-1].end]
    assert times == sorted(times)
    assert tr.text == "前面后面"
    assert tr.segments == [(0, 1), (2, 3)]


def test_json_roundtrip():
    tr = transcript_from_cues([Cue(0.0, 1.0, "好")])
    assert Transcript.from_json(tr.to_json()).text == "好"
