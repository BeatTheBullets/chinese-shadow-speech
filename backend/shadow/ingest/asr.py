from __future__ import annotations
import contextlib
import logging
import math
import os
import threading
import types
from fractions import Fraction
from pathlib import Path
from typing import Any, Protocol
from shadow.config import SegmentationCfg
from shadow.ingest.pauses import pause_ranges
from shadow.ingest.punct import Punctuator, punctuate_timed
from shadow.ingest.rectify import SENTENCE_END
from shadow.ingest.text import is_punct, to_simplified
from shadow.memory import trim_heap
from shadow.ingest.transcript import (
    Transcript, TimedChar, append_segment, chars_with_speech_times,
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


def _ascii_word_end(chars: list[TimedChar], i: int) -> bool:
    """`chars[i]` is an ASCII `.?!` the punctuation model wrote after an ASCII token (it writes `.` for `。`, `?` for
    `？` there): the speech char before it is an ASCII letter or digit and the next char does not go on the word."""
    if chars[i].c not in ".?!":
        return False
    k = i - 1
    while k >= 0 and is_punct(chars[k].c):
        k -= 1
    nxt = chars[i + 1].c if i + 1 < len(chars) else ""
    return k >= 0 and chars[k].c.isascii() and chars[k].c.isalnum() and not (nxt.isascii() and nxt.isalnum())


def sentence_ranges(chars: list[TimedChar]) -> list[tuple[int, int]]:
    """(first, last) char index per sentence: a sentence ends after a run of punctuation that holds sentence-final
    punctuation (rectify's SENTENCE_END, or an ASCII `.?!` after a Latin word: `_ascii_word_end`), so a closing
    quote stays with it; the rest is the last sentence."""
    out: list[tuple[int, int]] = []
    a = 0
    ended = False               # inside a run of punctuation that holds sentence-final punctuation
    for i, ch in enumerate(chars):
        ended = ch.c in SENTENCE_END or _ascii_word_end(chars, i) or (ended and is_punct(ch.c))
        nxt = chars[i + 1].c if i + 1 < len(chars) else ""
        if i == len(chars) - 1 or (ended and not is_punct(nxt)):
            out.append((a, i))
            a = i + 1
    return out


def _is_latin(ch: str) -> bool:
    return ch.isascii() and ch.isalpha()


def _inner_apostrophe(text: str, i: int) -> bool:
    """`text[i]` is an apostrophe inside a Latin word (don't, i'm, it's)."""
    return (text[i] == "'" and 0 < i < len(text) - 1 and _is_latin(text[i - 1]) and _is_latin(text[i + 1]))


def _has_punctuation(text: str) -> bool:
    """Any punctuation besides whitespace (an unpunctuated Paraformer result spaces its characters) and apostrophes
    inside Latin words (Paraformer's own tokens: don't, i'm)."""
    return any(is_punct(ch) and not ch.isspace() and not _inner_apostrophe(text, i) for i, ch in enumerate(text))


def _by_pauses(chars: list[TimedChar], pauses: SegmentationCfg) -> Transcript:
    tr = Transcript()
    for a, b in pause_ranges(chars, pauses):
        append_segment(tr, chars[a:b + 1])
    return tr


def _timing_units(text: str) -> list[tuple[int, bool]]:
    """(speech chars, timed) per Paraformer token of `text`, in order. A Latin word (letters, with apostrophes inside,
    e.g. "update", "don't", a merged "PPT") is one timed token, so is a hanzi or a digit; any other speech char (the
    "&" of AT&T) is a token Paraformer gives no timestamp (postprocess_utils.sentence_postprocess)."""
    units: list[tuple[int, bool]] = []
    i = 0
    while i < len(text):
        ch = text[i]
        if is_punct(ch):
            i += 1
        elif _is_latin(ch):
            j, n = i, 0
            while j < len(text) and (_is_latin(text[j]) or _inner_apostrophe(text, j)):
                n += 0 if is_punct(text[j]) else 1
                j += 1
            units.append((n, True))
            i = j
        else:
            units.append((1, not ch.isascii() or ch.isdigit()))
            i += 1
    return units


def _spread(a: float, b: float, n: int) -> list[tuple[float, float]]:
    """`n` equal consecutive parts of [a, b] ms, in seconds."""
    return [((a + (b - a) * k / n) / 1000, (a + (b - a) * (k + 1) / n) / 1000) for k in range(n)]


def _resampled(ts: list[list[float]], u: int) -> list[tuple[float, float]]:
    """(start, end) ms for `u` units laid proportionally over the `len(ts)` timestamps: unit i covers timestamp
    positions [i·T/u, (i+1)·T/u], each timestamp stretched over its own [start, end]; equals `ts` when u == T."""
    t = len(ts)

    def at(x: Fraction, k: int) -> float:
        a, b = ts[k]
        return a + float(x - k) * (b - a)
    out = []
    for i in range(u):
        x0, x1 = Fraction(i * t, u), Fraction((i + 1) * t, u)
        k0 = min(math.floor(x0), t - 1)
        k1 = max(math.ceil(x1) - 1, 0)
        out.append((at(x0, k0), at(x1, k1)))
    return out


def _speech_times(text: str, ts: list[list[float]]) -> tuple[list[tuple[float, float]], bool]:
    """One (start, end) in seconds per speech char of `text` from FunASR's timestamps (ms), and whether they pair
    exactly. Exactly: one timestamp per timed unit (`_timing_units`), a Latin word's letters sharing its timestamp
    evenly and an untimed char zero-length at the previous end. Otherwise (a token FunASR timed differently) the
    units are laid proportionally over the timestamps: approximate, but without the drift of FunASR's sentence_info."""
    units = _timing_units(text)
    timed = [n for n, is_timed in units if is_timed]
    exact = len(timed) == len(ts)
    if not ts:
        spans = [(0.0, 0.0)] * len(timed)
    elif exact:
        spans = [(a, b) for a, b in ts]
    else:
        spans = _resampled(ts, len(timed))
    out: list[tuple[float, float]] = []
    k = 0
    last = spans[0][0] / 1000 if spans else 0.0
    for n, is_timed in units:
        if is_timed:
            out.extend(_spread(spans[k][0], spans[k][1], n))
            k += 1
            last = out[-1][1]
        else:
            out.extend([(last, last)] * n)
    return out, exact


def transcript_from_funasr(result: dict[str, Any], pauses: SegmentationCfg | None = None) -> Transcript:
    """Chars from FunASR's top-level `text` + `timestamp` (one timestamp per hanzi, digit or Latin word: see
    `_timing_units`), split into sentences at sentence-final punctuation. Never from `sentence_info`: FunASR 1.4.16
    joins two Chinese VAD chunks without a space (auto_model._join_vad_texts), so their boundary chars become one
    token and its sentence builder pairs every later sentence's text one char further ahead of its punctuation and
    timestamps per VAD boundary (lessons drifted by a char per boundary; natural-speed videos with a Latin word,
    which used to be sent there, by up to ten chars and seconds). When the timestamps do not pair with the text's
    units, the units are laid proportionally over them, with a warning.
    With `pauses` and no punctuation in the text (the punctuation model is off), sentences are cut at pauses instead."""
    text = to_simplified(result.get("text") or "")
    by_pauses = pauses is not None and not _has_punctuation(text)
    ts = result.get("timestamp") or []
    if not any(not is_punct(ch) for ch in text):
        return Transcript()
    times, exact = _speech_times(text, ts)          # before the spaces between Latin words go
    if not exact:
        # never silently: its chars are only roughly where they are said
        log.warning("FunASR text has %d speech characters in %d timed units for %d timestamps; "
                    "laying them proportionally over the timestamps",
                    len(times), sum(1 for _, t in _timing_units(text) if t), len(ts))
    if by_pauses:
        text = "".join(text.split())
    chars = chars_with_speech_times(text, times, times[0][0])
    if by_pauses:
        return _by_pauses(chars, pauses)
    tr = Transcript()
    for a, b in sentence_ranges(chars):
        append_segment(tr, chars[a:b + 1])
    return tr


@contextlib.contextmanager
def _no_checkpoint_copy():
    """FunASR deep-copies the whole checkpoint (0.9 GB) before it reads it, which put the Paraformer load at 3.5 GB
    peak. The copy is only read, so for the duration of the load it is the checkpoint itself. A no-op if FunASR's
    loader looks different."""
    try:
        import importlib
        from shadow.hf import guarded_import
        lpm = guarded_import(lambda: importlib.import_module("funasr.train_utils.load_pretrained_model"))
        real = lpm.copy
    except Exception:
        yield
        return
    lpm.copy = types.SimpleNamespace(**{**vars(real), "deepcopy": lambda x, *a, **k: x})
    try:
        yield
    finally:
        lpm.copy = real


_MS_NAMES = {"fsmn-vad": "iic/speech_fsmn_vad_zh-cn-16k-common-pytorch"}   # FunASR's name_maps_ms entry
_MS_FILES = ("configuration.json", "config.yaml", "model.pt")


def _local_snapshot(name: str) -> str:
    """The cached ModelScope snapshot directory of `name` (a model id or a FunASR short name), or `name` itself when
    it is not (completely) on disk. Given an id, FunASR asks ModelScope for the file list before every load, so
    without the network a cached model fails to load ("not registered"); given a directory it reads it directly.
    "master" is the revision FunASR downloads. Not cached, or a lookup error: `name`, and FunASR downloads as before."""
    try:
        from shadow.hf import guarded_import

        def _import():
            from modelscope.hub.snapshot_download import snapshot_download
            return snapshot_download
        snapshot_download = guarded_import(_import)
        d = snapshot_download(_MS_NAMES.get(name, name), revision="master", local_files_only=True)
    except Exception:  # noqa: BLE001 - modelscope's "not cached" is a plain Exception
        return name
    return str(d) if all(os.path.isfile(os.path.join(d, f)) for f in _MS_FILES) else name


class ParaformerASR:
    """One recogniser shared by ingest jobs and attempt scoring: calls run one at a time."""
    def __init__(self, model_id: str, device: str, punctuator: Punctuator | None = None,
                 segmentation: SegmentationCfg | None = None, int8: bool = False):
        self.model_id, self.device, self.int8 = model_id, device, int8
        self.punctuator, self.segmentation = punctuator, segmentation
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
                kwargs: dict[str, Any] = {"model": _local_snapshot(self.model_id),
                                          "vad_model": _local_snapshot("fsmn-vad"), "device": self.device,
                                          "disable_update": True}
                if self.device == "cpu":            # FunASR sets torch's threads to ncpu (default 4): keep ours
                    import torch
                    kwargs["ncpu"] = torch.get_num_threads()
                with _no_checkpoint_copy():
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
                if self.punctuator is not None:
                    self._warm_punctuator()
        except Exception:
            log.exception("warming up the recogniser %s failed", self.model_id)
        finally:
            trim_heap()

    def transcribe(self, wav_path: Path) -> Transcript:
        with self._lock:
            return self._run(wav_path)

    def try_transcribe(self, wav_path: Path, timeout: float) -> Transcript | None:
        """None when the recogniser stays busy (another call holds it) for `timeout` seconds. The words check only
        needs the words: no punctuation."""
        if not self._lock.acquire(timeout=timeout):
            return None
        try:
            return self._run(wav_path, punctuate=False)
        finally:
            self._lock.release()

    def _warm_punctuator(self) -> bool:
        """Load the punctuation model now (download, checksum, import), so a failure shows up in seconds and not after
        the transcription. False when it cannot load: the caller cuts sentences at pauses instead."""
        load = getattr(self.punctuator, "_load", None)
        if load is None:
            return True
        try:
            load()
            return True
        except Exception:
            log.warning("the punctuation model could not be loaded; cutting sentences at pauses instead", exc_info=True)
            return False

    def _run(self, wav_path: Path, punctuate: bool = True) -> Transcript:
        use_punct = self.punctuator is not None and punctuate and self._warm_punctuator()
        res = self._load().generate(input=str(wav_path), sentence_timestamp=True, batch_size_s=300)
        r = res[0] if res else {"text": ""}
        cfg = self.segmentation or SegmentationCfg()
        if not use_punct:       # FunASR's text is unpunctuated: cut at pauses (if configured)
            return transcript_from_funasr(r, pauses=self.segmentation)
        try:
            text = to_simplified(r.get("text") or "")
            punctuated = punctuate_timed(text, r.get("timestamp") or [], self.punctuator, cfg)
        except Exception:
            log.warning("punctuation failed; cutting sentences at pauses instead", exc_info=True)
            return transcript_from_funasr(r, pauses=cfg)
        # pauses as a safety net: text the model left unpunctuated (every chunk failed) still splits
        return transcript_from_funasr({**r, "text": punctuated}, pauses=self.segmentation)


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
