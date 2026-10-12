import pytest

from shadow.ingest.asr import transcript_from_funasr, FakeASR
from shadow.ingest.transcript import Transcript


def test_funasr_sentence_info_with_matching_timestamps():
    result = {
        "text": "你好，世界。再见。",
        "sentence_info": [
            {"text": "你好，世界。", "start": 1000, "end": 2000,
             "timestamp": [[1000, 1200], [1200, 1400], [1500, 1700], [1700, 2000]]},
            {"text": "再见。", "start": 2500, "end": 3000, "timestamp": [[2500, 2700], [2700, 3000]]},
        ],
    }
    tr = transcript_from_funasr(result)
    assert tr.text == "你好，世界。再见。"
    assert tr.chars[0].start == 1.0 and tr.chars[3].end == 1.7 and tr.chars[4].end == 2.0
    assert tr.chars[2].start == tr.chars[2].end == 1.4           # comma zero-length
    assert tr.segments == [(0, 5), (6, 8)]


def test_funasr_timestamp_count_mismatch_falls_back_to_interpolation():
    result = {"text": "你好世界", "sentence_info": [{"text": "你好世界", "start": 0, "end": 2000, "timestamp": [[0, 500]]}]}
    tr = transcript_from_funasr(result)
    assert [round(c.start, 2) for c in tr.chars] == [0.0, 0.5, 1.0, 1.5]


def test_funasr_without_sentence_info_uses_whole_text():
    tr = transcript_from_funasr({"text": "大家好", "timestamp": [[0, 300], [300, 600], [600, 900]]})
    assert tr.text == "大家好" and tr.chars[2].end == 0.9 and tr.segments == [(0, 2)]


def test_funasr_empty_text_gives_empty_transcript():
    tr = transcript_from_funasr({"text": "", "sentence_info": []})
    assert tr.chars == [] and tr.segments == []


def test_fake_asr_returns_given_transcript(tmp_path):
    tr = Transcript()
    assert FakeASR(tr).transcribe(tmp_path / "x.wav") is tr


@pytest.mark.models
def test_paraformer_real(tmp_path):
    from shadow.ingest.asr import ParaformerASR
    from tests.helpers import make_tone_wav
    asr = ParaformerASR("iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch", "cpu")
    tr = asr.transcribe(make_tone_wav(tmp_path / "t.wav", 2.0))
    assert isinstance(tr, Transcript)


def test_asr_hearer_returns_the_recognised_text_with_punctuation(tmp_path):
    from shadow.ingest.asr import AsrHearer, FakeHearer
    tr = transcript_from_funasr({"text": "我是学生。", "timestamp": [[0, 100], [100, 200], [200, 300], [300, 400]]})
    assert AsrHearer(FakeASR(tr)).hear(tmp_path / "x.wav") == "我是学生。"
    assert FakeHearer("你好").hear(tmp_path / "x.wav") == "你好"


def test_paraformer_calls_run_one_at_a_time(tmp_path):
    """Ingest jobs and attempt scoring share one recogniser."""
    import threading, time
    from shadow.ingest.asr import ParaformerASR

    class Slow:
        def __init__(self): self.active = 0; self.peak = 0
        def generate(self, **kw):
            self.active += 1; self.peak = max(self.peak, self.active); time.sleep(0.05); self.active -= 1
            return [{"text": ""}]

    asr = ParaformerASR("none", "cpu"); asr._model = inner = Slow()
    ts = [threading.Thread(target=asr.transcribe, args=(tmp_path / "x.wav",)) for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert inner.peak == 1


def _client_with_asr(data_dir, asr):
    from fastapi.testclient import TestClient
    from shadow.config import Settings
    from shadow.deps import fake_deps
    from shadow.main import create_app
    s = Settings(data_dir=data_dir)
    deps = fake_deps(s, Transcript()); deps.asr = asr
    return TestClient(create_app(s, deps=deps))


def test_the_recogniser_warms_up_at_start_up(data_dir, monkeypatch):
    import threading
    from shadow.ingest.asr import ParaformerASR
    loaded = threading.Event()

    def load(self):
        assert self._lock.locked(); loaded.set()
    monkeypatch.setattr(ParaformerASR, "_load", load)
    with _client_with_asr(data_dir, ParaformerASR("none", "cpu")):
        assert loaded.wait(5)


def test_a_failed_recogniser_warm_up_is_logged_not_raised(data_dir, monkeypatch, caplog):
    import threading
    from shadow.ingest.asr import ParaformerASR
    tried = threading.Event()

    def load(self):
        tried.set(); raise OSError("offline")
    monkeypatch.setattr(ParaformerASR, "_load", load)
    with _client_with_asr(data_dir, ParaformerASR("none", "cpu")) as c:
        assert tried.wait(5)
        assert c.get("/health").status_code == 200
    for _ in range(50):
        if "warming up" in caplog.text:
            break
        threading.Event().wait(0.02)
    assert "warming up the recogniser" in caplog.text and "offline" in caplog.text


def test_real_deps_hear_takes_with_the_ingest_recogniser_and_fake_deps_do_not(tmp_path):
    from shadow.config import Settings
    from shadow.deps import build_deps, fake_deps
    from shadow.ingest.asr import AsrHearer
    s = Settings(data_dir=tmp_path)
    real = build_deps(s)
    assert isinstance(real.hearer, AsrHearer) and real.hearer.asr is real.asr
    assert fake_deps(s, Transcript()).hearer is None
