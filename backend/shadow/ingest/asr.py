from __future__ import annotations
import logging
import threading
from pathlib import Path
from typing import Any, Protocol
from shadow.ingest.rectify import SENTENCE_END
from shadow.ingest.text import is_punct, to_simplified
from shadow.memory import trim_heap
from shadow.ingest.transcript import (
    Transcript, TimedChar, append_segment, chars_with_interpolated_times, chars_with_speech_times,
)

log = logging.getLogger(__name__)
HEAR_WAIT_S = 2.0          # a take waits at most this long for the recogniser (an ingest job holds it for a whole video)


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
    # never silently: spread over the sentence, its chars are only roughly where they are said
    log.warning("FunASR sentence %r has %d speech characters for %d timestamps; interpolating its times",
                text, speech_count, len(ts or []))
    return chars_with_interpolated_times(text, start_ms / 1000, end_ms / 1000)


def sentence_ranges(chars: list[TimedChar]) -> list[tuple[int, int]]:
    """(first, last) char index per sentence: a sentence ends after a run of punctuation that holds sentence-final
    punctuation (rectify's SENTENCE_END), so a closing quote stays with it; the rest is the last sentence."""
    out: list[tuple[int, int]] = []
    a = 0
    ended = False               # inside a run of punctuation that holds sentence-final punctuation
    for i, ch in enumerate(chars):
        ended = ch.c in SENTENCE_END or (ended and is_punct(ch.c))
        nxt = chars[i + 1].c if i + 1 < len(chars) else ""
        if i == len(chars) - 1 or (ended and not is_punct(nxt)):
            out.append((a, i))
            a = i + 1
    return out


def _from_sentence_info(result: dict[str, Any]) -> Transcript:
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


def transcript_from_funasr(result: dict[str, Any]) -> Transcript:
    """Chars from FunASR's top-level `text` + `timestamp` (one timestamp per speech char), split into sentences at
    sentence-final punctuation. Not from `sentence_info`: FunASR 1.4.16 joins two Chinese VAD chunks without a space
    (auto_model._join_vad_texts), so their boundary chars become one token and its sentence builder pairs every
    later sentence's text one char ahead of its timestamps (lessons drifted by a char per VAD boundary). Only when
    the top-level counts disagree (e.g. Latin words, timed per word) is `sentence_info` used, with a warning."""
    text = to_simplified(result.get("text") or "")
    ts = result.get("timestamp") or []
    speech_count = sum(1 for ch in text if not is_punct(ch))
    if speech_count and speech_count == len(ts):
        chars = chars_with_speech_times(text, [(a / 1000, b / 1000) for a, b in ts], ts[0][0] / 1000)
        tr = Transcript()
        for a, b in sentence_ranges(chars):
            append_segment(tr, chars[a:b + 1])
        return tr
    if speech_count:
        log.warning("FunASR text has %d speech characters for %d timestamps; using its sentence_info",
                    speech_count, len(ts))
    return _from_sentence_info(result)


class ParaformerASR:
    """One recogniser shared by ingest jobs and attempt scoring: calls run one at a time."""
    def __init__(self, model_id: str, device: str):
        self.model_id, self.device = model_id, device
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            from shadow.hf import guarded_import, model_load_lock

            def _import_funasr():
                from funasr import AutoModel
                return AutoModel
            AutoModel = guarded_import(_import_funasr)
            with model_load_lock:
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
            finally:
                trim_heap()
        t = threading.Thread(target=run, name="asr-warm-up", daemon=True)
        t.start()
        return t

    def transcribe(self, wav_path: Path) -> Transcript:
        with self._lock:
            return self._run(wav_path)

    def try_transcribe(self, wav_path: Path, timeout: float) -> Transcript | None:
        """None when the recogniser stays busy (another call holds it) for `timeout` seconds."""
        if not self._lock.acquire(timeout=timeout):
            return None
        try:
            return self._run(wav_path)
        finally:
            self._lock.release()

    def _run(self, wav_path: Path) -> Transcript:
        res = self._load().generate(input=str(wav_path), sentence_timestamp=True, batch_size_s=300)
        return transcript_from_funasr(res[0] if res else {"text": ""})


class Hearer(Protocol):
    """What a take says, as text (Phase 2 spec §1): the words check of attempt scoring. None: not heard (busy)."""
    def hear(self, wav_path: Path) -> str | None: ...


class AsrHearer:
    def __init__(self, asr: ParaformerASR):
        self.asr = asr

    def hear(self, wav_path: Path) -> str | None:
        tr = self.asr.try_transcribe(wav_path, HEAR_WAIT_S)
        return None if tr is None else tr.text.strip()


class FakeHearer:
    def __init__(self, text: str):
        self.text = text

    def hear(self, wav_path: Path) -> str | None:
        return self.text
