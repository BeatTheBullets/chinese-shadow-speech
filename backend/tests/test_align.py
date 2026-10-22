import logging
from types import SimpleNamespace
import numpy as np
import pytest
from shadow.ingest.align import (FakeAligner, MmsAligner, Qwen3Aligner, align_in_window, make_aligner,
                                 romanise_for_mms, sentence_bounds)


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


# --- Qwen3Aligner item mapping (stub model, no qwen install) ---
def _item(text, start, end):
    return SimpleNamespace(text=text, start_time=start, end_time=end)


class _StubQwen:
    def __init__(self, items):
        self.items = items

    def align(self, audio, text, language):
        return [self.items]


def _qwen(items):
    a = Qwen3Aligner("cpu")
    a._model = _StubQwen(items)
    return a


WAV = np.zeros(16000 * 7, dtype="float32")


def test_qwen_merged_digit_and_latin_items_split_per_char():
    items = [_item("2024", 0.0, 2.0), _item("年", 2.0, 2.5), _item("用", 2.5, 3.0), _item("ai", 3.0, 4.0)]
    spans = _qwen(items).align(WAV, 16000, "2024年用AI")
    assert [s.ch for s in spans] == list("2024年用AI")
    assert [round(s.start, 3) for s in spans[:4]] == [0.0, 0.5, 1.0, 1.5]
    assert (spans[3].end, spans[4].start, spans[5].start) == (2.0, 2.0, 2.5)
    assert (spans[6].start, spans[6].end, spans[7].start, spans[7].end) == (3.0, 3.5, 3.5, 4.0)
    assert all(s.conf == 1.0 for s in spans)


def test_qwen_dropped_char_gets_zero_length_conf0_span():
    items = [_item("涨", 0.0, 0.5), _item("了", 0.5, 1.0), _item("5", 1.0, 1.5), _item("倍", 1.5, 2.0)]
    spans = _qwen(items).align(WAV, 16000, "涨了5%倍")
    assert [s.ch for s in spans] == list("涨了5%倍")
    assert (spans[3].start, spans[3].end, spans[3].conf) == (1.5, 1.5, 0.0)
    assert spans[4].start == 1.5 and spans[4].conf == 1.0


def test_qwen_leading_and_trailing_dropped_chars():
    items = [_item("你", 1.0, 1.5), _item("好", 1.5, 2.0)]
    spans = _qwen(items).align(WAV, 16000, "%你好℃")
    assert [(s.ch, s.start, s.end, s.conf) for s in spans] == [
        ("%", 1.0, 1.0, 0.0), ("你", 1.0, 1.5, 1.0), ("好", 1.5, 2.0, 1.0), ("℃", 2.0, 2.0, 0.0)]


def test_qwen_genuine_mismatch_falls_back_uniform_conf0_and_warns(caplog):
    items = [_item("你", 0.0, 1.0)]       # 好 and 吗 missing: cannot be mapped
    with caplog.at_level(logging.WARNING, logger="shadow.ingest.align"):
        spans = _qwen(items).align(np.zeros(16000 * 3, dtype="float32"), 16000, "你好吗")
    assert [s.ch for s in spans] == list("你好吗")
    assert all(s.conf == 0.0 for s in spans)
    assert abs(spans[1].start - 1.0) < 1e-6 and abs(spans[-1].end - 3.0) < 1e-6
    assert any(r.levelno == logging.WARNING for r in caplog.records)


def test_qwen_device_map_passes_cuda_index():
    assert Qwen3Aligner("cuda")._device_map() == "cuda:0"
    assert Qwen3Aligner("cuda:1")._device_map() == "cuda:1"
    assert Qwen3Aligner("cpu")._device_map() == "cpu"


def test_make_aligner_resolves_names_without_loading_models():
    assert isinstance(make_aligner("fake", "cpu"), FakeAligner)
    m = make_aligner("mms_fa", "cpu")
    assert isinstance(m, MmsAligner) and m._model is None
    q = make_aligner("qwen3_fa", "cpu")
    assert isinstance(q, Qwen3Aligner) and q._model is None
    with pytest.raises(ValueError):
        make_aligner("nope", "cpu")


def test_locked_aligner_serialises_calls():
    import threading, time
    import numpy as np
    from shadow.ingest.align import LockedAligner

    class Slow:
        _model = "m"
        def __init__(self): self.active = 0; self.peak = 0
        def align(self, wav, sr, text):
            self.active += 1; self.peak = max(self.peak, self.active); time.sleep(0.05); self.active -= 1
            return []

    inner = Slow(); la = LockedAligner(inner)
    ts = [threading.Thread(target=la.align, args=(np.zeros(10), 16000, "我")) for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert inner.peak == 1 and la._model == "m"


def test_mms_letter_ids_and_blank_need_no_model():
    m = MmsAligner("cpu")
    d = {'-': 0, 'a': 1, 'i': 2, 'h': 15, 'c': 20, 'u': 6, 'l': 12}
    assert m.blank == 0
    assert m.letter_ids("chi") == [d["c"], d["h"], d["i"]]
    assert m.letter_ids("lv") == [d["l"], d["u"]]       # ü (v) is spelled u, as romanise_for_mms does
    assert m.letter_ids("") == [d["a"]]
    assert m._model is None


def test_locked_aligner_forwards_sound_calls_under_its_lock():
    import numpy as np
    from shadow.ingest.align import LockedAligner

    class Inner:
        blank = 7
        def __init__(self): self.locked = []
        def emissions(self, wav, sr): self.locked.append(la._lock.locked()); return "E", 0.02
        def letter_ids(self, s): self.locked.append(la._lock.locked()); return [1]

    inner = Inner(); la = LockedAligner(inner)
    assert la.emissions(np.zeros(1), 16000) == ("E", 0.02)
    assert la.letter_ids("a") == [1]
    assert la.blank == 7 and la.inner is inner
    assert inner.locked == [True, True]
