import numpy as np
from shadow.ingest.align import FakeAligner, align_in_window, sentence_bounds, romanise_for_mms


def test_fake_aligner_uniform_spans_skip_punct():
    wav = np.zeros(16000, dtype="float32")
    spans = FakeAligner().align(wav, 16000, "你好，世界。")
    assert [s.ch for s in spans] == ["你", "好", "世", "界"]
    assert spans[0].start == 0.0 and abs(spans[-1].end - 1.0) < 1e-6


def test_align_in_window_offsets_to_absolute():
    wav = np.zeros(16000 * 10, dtype="float32")
    spans = align_in_window(FakeAligner(), wav, 16000, "你好", 4.0, 6.0)
    assert abs(spans[0].start - 4.0) < 1e-6 and abs(spans[-1].end - 6.0) < 1e-6


def test_sentence_bounds_pad_and_clamp():
    from shadow.ingest.align import Span
    spans = [Span("你", 1.0, 1.4, 1.0), Span("好", 1.4, 1.9, 1.0)]
    assert sentence_bounds(spans, 0.12, prev_end=0.0, next_start=10.0, total=20.0) == (0.88, 2.02)
    assert sentence_bounds(spans, 0.12, prev_end=0.95, next_start=1.95, total=20.0) == (0.95, 1.95)
    assert sentence_bounds(spans, 0.12, prev_end=0.0, next_start=10.0, total=1.95) == (0.88, 1.95)


def test_romanise_for_mms():
    assert romanise_for_mms("你好，绿") == ["ni", "hao", "lu"]
