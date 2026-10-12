from __future__ import annotations
import logging
import threading
from pathlib import Path
from typing import Any, Protocol
from shadow.ingest.text import is_punct, to_simplified
from shadow.ingest.transcript import (
    Transcript, TimedChar, append_segment, chars_with_interpolated_times, chars_with_speech_times,
)

log = logging.getLogger(__name__)


class ASR(Protocol):
    def transcribe(self, wav_path: Path) -> Transcript: ...


class FakeASR:
    def __init__(self, transcript: Transcript):
        self._tr = transcript

    def transcribe(self, wav_path: Path) -> Transcript:
        return self._tr


def _sentence_chars(text: str, start_ms: float, end_ms: float, ts: list[list[float]] | None) -> list[TimedChar]:
    text = to_simplified(text)
    speech_count = sum(1 for ch in text if not is_punct(ch))
    if ts and len(ts) == speech_count:
        speech_times = [(a / 1000, b / 1000) for a, b in ts]
        return chars_with_speech_times(text, speech_times, start_ms / 1000)
    return chars_with_interpolated_times(text, start_ms / 1000, end_ms / 1000)


def transcript_from_funasr(result: dict[str, Any]) -> Transcript:
    tr = Transcript()
    sentences = result.get("sentence_info") or []
    if not sentences:
        text = result.get("text") or ""
        if not text.strip():
            return tr
        ts = result.get("timestamp")
        end_ms = ts[-1][1] if ts else 0
        start_ms = ts[0][0] if ts else 0
        sentences = [{"text": text, "start": start_ms, "end": end_ms, "timestamp": ts}]
    for s in sentences:
        append_segment(
            tr, _sentence_chars(s.get("text", ""), float(s.get("start", 0)), float(s.get("end", 0)), s.get("timestamp"))
        )
    return tr


class ParaformerASR:
    """One recogniser shared by ingest jobs and attempt scoring: calls run one at a time."""
    def __init__(self, model_id: str, device: str):
        self.model_id, self.device = model_id, device
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            from funasr import AutoModel
            self._model = AutoModel(model=self.model_id, vad_model="fsmn-vad", punc_model="ct-punc",
                                    device=self.device, disable_update=True)
        return self._model

    def warm_up(self) -> threading.Thread:
        """Load (on first run: download) the model in a daemon thread, so the first take's words check does not
        wait for it; under the lock, like the embedder's warm-up. A failure is logged and the next call tries again."""
        def run():
            try:
                with self._lock:
                    self._load()
            except Exception:
                log.exception("warming up the recogniser %s failed", self.model_id)
        t = threading.Thread(target=run, name="asr-warm-up", daemon=True)
        t.start()
        return t

    def transcribe(self, wav_path: Path) -> Transcript:
        with self._lock:
            res = self._load().generate(input=str(wav_path), sentence_timestamp=True, batch_size_s=300)
        return transcript_from_funasr(res[0] if res else {"text": ""})


class Hearer(Protocol):
    """What a take says, as text (Phase 2 spec §1): the words check of attempt scoring."""
    def hear(self, wav_path: Path) -> str: ...


class AsrHearer:
    def __init__(self, asr: ASR):
        self.asr = asr

    def hear(self, wav_path: Path) -> str:
        return self.asr.transcribe(wav_path).text


class FakeHearer:
    def __init__(self, text: str):
        self.text = text

    def hear(self, wav_path: Path) -> str:
        return self.text
