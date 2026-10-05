import random
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


def test_monotonicity_with_floating_point_edge_cases():
    """Test monotonicity with overlapping, out-of-order, and zero-length cues.

    Includes edge case with long float tail (5.504302933841399) followed by
    overlapping cue, and validates that:
    - Every char has end >= start
    - Every consecutive pair maintains prev.end <= next.start
    - Every consecutive pair maintains prev.start <= next.start
    """
    # Test specific edge case from bug report
    tr = transcript_from_cues([
        Cue(1.922, 5.504302933841399, "们你我吗你。吗。"),
        Cue(5.027, 9.78, "后续文本")
    ])
    _assert_transcript_monotonic(tr)

    # Random test with seeded randomness (2000 cases)
    random.seed(1)
    for _ in range(2000):
        cues = _generate_random_cues(random)
        tr = transcript_from_cues(cues)
        _assert_transcript_monotonic(tr)


def _generate_random_cues(rng) -> list[Cue]:
    """Generate random cues for monotonicity testing."""
    num_cues = rng.randint(1, 5)
    cues = []

    # Generate base time points
    times = sorted([rng.uniform(0, 20) for _ in range(num_cues * 2)])

    for i in range(num_cues):
        start = times[i]
        end = times[i + num_cues]
        # Ensure end > start
        if end <= start:
            end = start + rng.uniform(0.1, 2.0)

        # Random text: mix of speech and punctuation
        text = ""
        for _ in range(rng.randint(1, 6)):
            if rng.random() < 0.8:
                text += chr(0x4E00 + rng.randint(0, 20000))  # Random CJK char
            else:
                text += rng.choice("。，！？；：、")  # Random punctuation

        cues.append(Cue(start, end, text))

    # Sometimes shuffle to make them out-of-order
    if rng.random() < 0.5:
        rng.shuffle(cues)

    return cues


def _assert_transcript_monotonic(tr: Transcript) -> None:
    """Assert that a transcript maintains monotonicity invariants."""
    # Every char must have end >= start
    for i, c in enumerate(tr.chars):
        assert c.end >= c.start, f"Char {i} ({c.c!r}): end ({c.end}) < start ({c.start})"

    # Every consecutive pair must maintain prev.end <= next.start
    for i in range(len(tr.chars) - 1):
        prev = tr.chars[i]
        next_c = tr.chars[i + 1]
        assert prev.end <= next_c.start, (
            f"Chars {i}-{i+1}: prev.end ({prev.end}) > next.start ({next_c.start})"
        )

    # Every consecutive pair must maintain prev.start <= next.start
    for i in range(len(tr.chars) - 1):
        prev = tr.chars[i]
        next_c = tr.chars[i + 1]
        assert prev.start <= next_c.start, (
            f"Chars {i}-{i+1}: prev.start ({prev.start}) > next.start ({next_c.start})"
        )
