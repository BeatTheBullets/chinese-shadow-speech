from __future__ import annotations
import logging
import threading
from dataclasses import dataclass
from typing import Protocol
import numpy as np
from pypinyin import lazy_pinyin, Style
from shadow.ingest.text import is_punct

log = logging.getLogger(__name__)


@dataclass
class Span:
    ch: str
    start: float
    end: float
    conf: float


class Aligner(Protocol):
    def align(self, wav: np.ndarray, sr: int, text: str) -> list[Span]: ...


class LockedAligner:
    """One aligner shared by ingest jobs and attempt scoring (Phase 2 spec §1 step 3): calls run one at a time."""
    def __init__(self, inner: Aligner):
        self.inner = inner
        self._lock = threading.Lock()

    @property
    def _model(self):                   # Deps.loaded_models() looks for it
        return getattr(self.inner, "_model", None)

    def align(self, wav: np.ndarray, sr: int, text: str) -> list[Span]:
        with self._lock:
            return self.inner.align(wav, sr, text)


def speech_chars(text: str) -> list[str]:
    return [c for c in text if not is_punct(c)]


def romanise_for_mms(text: str) -> list[str]:
    out = []
    for p in lazy_pinyin(speech_chars(text), style=Style.NORMAL):
        p = p.replace("ü", "u").replace("v", "u")
        out.append("".join(ch for ch in p.lower() if "a" <= ch <= "z") or "a")
    return out


class FakeAligner:
    def align(self, wav: np.ndarray, sr: int, text: str) -> list[Span]:
        chars = speech_chars(text)
        dur = len(wav) / sr
        n = max(len(chars), 1)
        return [Span(c, i * dur / n, (i + 1) * dur / n, 1.0) for i, c in enumerate(chars)]


class MmsAligner:
    def __init__(self, device: str):
        self.device = device
        self._bundle = self._model = self._tok = self._al = None

    def _load(self):
        if self._model is None:
            import torchaudio
            self._bundle = torchaudio.pipelines.MMS_FA
            self._model = self._bundle.get_model(with_star=False).to(self.device).eval()
            self._tok = self._bundle.get_tokenizer()
            self._al = self._bundle.get_aligner()
        return self._model

    def align(self, wav: np.ndarray, sr: int, text: str) -> list[Span]:
        import torch
        model = self._load()
        chars = speech_chars(text)
        if not chars:
            return []
        words = romanise_for_mms(text)
        x = torch.from_numpy(wav).float().unsqueeze(0).to(self.device)
        if sr != self._bundle.sample_rate:
            import torchaudio.functional as F
            x = F.resample(x, sr, self._bundle.sample_rate)
        with torch.inference_mode():
            emission, _ = model(x)
        token_spans = self._al(emission[0], self._tok(words))
        ratio = x.size(1) / emission.size(1) / self._bundle.sample_rate
        out: list[Span] = []
        for ch, spans in zip(chars, token_spans, strict=True):
            out.append(Span(ch, spans[0].start * ratio, spans[-1].end * ratio,
                            float(sum(s.score for s in spans) / len(spans))))
        return out


class Qwen3Aligner:
    def __init__(self, device: str):
        self.device = device
        self._model = None

    def _device_map(self) -> str:
        if self.device == "cuda":
            return "cuda:0"
        return self.device if self.device.startswith("cuda") else "cpu"

    def _load(self):
        if self._model is None:
            import torch
            from qwen_asr import Qwen3ForcedAligner
            self._model = Qwen3ForcedAligner.from_pretrained(
                "Qwen/Qwen3-ForcedAligner-0.6B", dtype=torch.bfloat16,
                device_map=self._device_map())
        return self._model

    def align(self, wav: np.ndarray, sr: int, text: str) -> list[Span]:
        chars = speech_chars(text)
        if not chars:
            return []
        results = self._load().align(audio=(wav, sr), text="".join(chars), language="Chinese")
        spans = _map_items_to_chars(results[0], chars)
        if spans is None:                     # genuine mismatch: uniform timing, flagged by conf=0.0
            log.warning("Qwen3 alignment could not be mapped to %d characters; using uniform timing", len(chars))
            return [Span(s.ch, s.start, s.end, 0.0) for s in FakeAligner().align(wav, sr, text)]
        return spans


def _map_items_to_chars(items, chars: list[str]) -> list[Span] | None:
    """Map aligner items (CJK chars one by one, letter/digit runs merged, some chars dropped)
    back onto `chars`. Returns None when the items cannot be matched in order."""
    items = [it for it in items if it.text and not all(is_punct(c) for c in it.text)]
    out: list[Span | None] = [None] * len(chars)
    j = 0
    for it in items:
        want = it.text.lower()
        k = j
        while k < len(chars) and "".join(chars[k:k + len(want)]).lower() != want:
            if chars[k].isalnum():            # the aligner only drops non-letter/number chars
                return None
            k += 1
        if k >= len(chars):
            return None
        n = len(want)
        start, end = float(it.start_time), float(it.end_time)
        step = (end - start) / n
        for i in range(n):
            out[k + i] = Span(chars[k + i], start + i * step, start + (i + 1) * step, 1.0)
        j = k + n
    if any(c.isalnum() for c in chars[j:]) or not any(out):
        return None
    for i, sp in enumerate(out):              # dropped chars: zero-length, conf 0.0
        if sp is None:
            prev = next((out[p] for p in range(i - 1, -1, -1) if out[p]), None)
            t = prev.end if prev else next(o.start for o in out[i:] if o)
            out[i] = Span(chars[i], t, t, 0.0)
    return out  # type: ignore[return-value]


def make_aligner(name: str, device: str) -> Aligner:
    if name == "qwen3_fa":
        return Qwen3Aligner(device)
    if name == "mms_fa":
        return MmsAligner(device)
    if name == "fake":
        return FakeAligner()
    raise ValueError(f"unknown aligner {name}")


def align_in_window(aligner: Aligner, wav: np.ndarray, sr: int, text: str,
                    win_start: float, win_end: float) -> list[Span]:
    a = max(0, int(win_start * sr))
    b = min(len(wav), int(win_end * sr))
    spans = aligner.align(wav[a:b], sr, text)
    off = a / sr
    return [Span(s.ch, s.start + off, s.end + off, s.conf) for s in spans]


def sentence_bounds(spans: list[Span], pad_s: float, prev_end: float, next_start: float, total: float) -> tuple[float, float]:
    start = max(spans[0].start - pad_s, prev_end, 0.0)
    end = min(spans[-1].end + pad_s, next_start, total)
    return (round(start, 3), round(max(end, start), 3))


def spans_to_json(spans: list[Span]) -> list[dict]:
    """Serialise spans for `Segment.ref_alignment_json`."""
    return [{"ch": s.ch, "start": round(s.start, 3), "end": round(s.end, 3), "conf": round(s.conf, 3)} for s in spans]
