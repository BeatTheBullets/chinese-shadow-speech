from __future__ import annotations
import logging
import threading
from pathlib import Path
from typing import Any, Protocol
from shadow.config import SegmentationCfg
from shadow.ingest.pauses import pause_ranges
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


def _has_punctuation(text: str) -> bool:
    """Any punctuation besides whitespace (an unpunctuated Paraformer result spaces its characters)."""
    return any(is_punct(ch) and not ch.isspace() for ch in text)


def _by_pauses(chars: list[TimedChar], pauses: SegmentationCfg) -> Transcript:
    tr = Transcript()
    for a, b in pause_ranges(chars, pauses):
        append_segment(tr, chars[a:b + 1])
    return tr


def _from_sentence_info(result: dict[str, Any], pauses: SegmentationCfg | None = None) -> Transcript:
    tr = Transcript()
    unpunctuated = pauses is not None and not _has_punctuation(result.get("text") or "")
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
        text = s.get("text", "")
        if unpunctuated:
            text = "".join(text.split())
        append_segment(
            tr, _sentence_chars(text, float(s.get("start", 0)), float(s.get("end", 0)), s.get("timestamp"))
        )
    return _by_pauses(tr.chars, pauses) if unpunctuated else tr


def _is_latin(ch: str) -> bool:
    return ch.isascii() and ch.isalpha()


def _timing_units(text: str) -> list[int]:
    """Speech chars per FunASR timestamp, in order: Paraformer times a Latin word (letters, with apostrophes inside,
    e.g. "update", "don't", a merged "PPT") as one token and every other speech char (a hanzi, a digit) as one."""
    units: list[int] = []
    i = 0
    while i < len(text):
        if is_punct(text[i]):
            i += 1
        elif _is_latin(text[i]):
            j, n = i, 0
            while j < len(text) and (_is_latin(text[j]) or (
                    text[j] == "'" and j + 1 < len(text) and _is_latin(text[j + 1]))):
                n += 0 if is_punct(text[j]) else 1
                j += 1
            units.append(n)
            i = j
        else:
            units.append(1)
            i += 1
    return units


def _speech_times(text: str, ts: list[list[float]]) -> list[tuple[float, float]] | None:
    """One (start, end) in seconds per speech char of `text` from FunASR's timestamps (ms): one timestamp per speech
    char, or else one per timing unit with a Latin word's letters sharing its timestamp evenly; None if neither fits."""
    if sum(1 for ch in text if not is_punct(ch)) == len(ts):
        return [(a / 1000, b / 1000) for a, b in ts]
    units = _timing_units(text)
    if len(units) != len(ts):
        return None
    out: list[tuple[float, float]] = []
    for n, (a, b) in zip(units, ts):
        out.extend(((a + (b - a) * k / n) / 1000, (a + (b - a) * (k + 1) / n) / 1000) for k in range(n))
    return out


def transcript_from_funasr(result: dict[str, Any], pauses: SegmentationCfg | None = None) -> Transcript:
    """Chars from FunASR's top-level `text` + `timestamp` (one timestamp per speech char, or per Latin word: see
    `_timing_units`), split into sentences at sentence-final punctuation. Not from `sentence_info`: FunASR 1.4.16
    joins two Chinese VAD chunks without a space (auto_model._join_vad_texts), so their boundary chars become one
    token and its sentence builder pairs every later sentence's text one char further ahead of its punctuation and
    timestamps per VAD boundary (lessons drifted by a char per boundary; a natural-speed video with one Latin word,
    which used to send it here, drifted by up to ten chars and seconds). Only when the top-level counts still
    disagree is `sentence_info` used, with a warning.
    With `pauses` and no punctuation in the text (the punctuation model is off), sentences are cut at pauses instead."""
    text = to_simplified(result.get("text") or "")
    by_pauses = pauses is not None and not _has_punctuation(text)
    ts = result.get("timestamp") or []
    speech_count = sum(1 for ch in text if not is_punct(ch))
    times = _speech_times(text, ts) if speech_count else None      # before the spaces between Latin words go
    if by_pauses:
        text = "".join(text.split())
    if times is not None:
        chars = chars_with_speech_times(text, times, times[0][0])
        if by_pauses:
            return _by_pauses(chars, pauses)
        tr = Transcript()
        for a, b in sentence_ranges(chars):
            append_segment(tr, chars[a:b + 1])
        return tr
    if speech_count:
        log.warning("FunASR text has %d speech characters for %d timestamps; using its sentence_info",
                    speech_count, len(ts))
    return _from_sentence_info(result, pauses)


class ParaformerASR:
    """One recogniser shared by ingest jobs and attempt scoring: calls run one at a time."""
    def __init__(self, model_id: str, device: str, punctuation: bool = True,
                 segmentation: SegmentationCfg | None = None, int8: bool = False):
        self.model_id, self.device, self.int8 = model_id, device, int8
        self.punctuation, self.segmentation = punctuation, segmentation
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
                kwargs: dict[str, Any] = {"model": self.model_id, "vad_model": "fsmn-vad", "device": self.device,
                                          "disable_update": True}
                if self.punctuation:
                    kwargs["punc_model"] = "ct-punc"
                model = AutoModel(**kwargs)
                if self.int8:
                    from shadow.quant import quantize_linear
                    model.model = quantize_linear(model.model)
                self._model = model
        return self._model

    def warm(self) -> None:
        """Blocking load under the lock, like the embedder's; a failure is logged and the next call tries again."""
        try:
            with self._lock:
                self._load()
        except Exception:
            log.exception("warming up the recogniser %s failed", self.model_id)
        finally:
            trim_heap()

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
        pauses = None if self.punctuation else self.segmentation
        return transcript_from_funasr(res[0] if res else {"text": ""}, pauses=pauses)


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
