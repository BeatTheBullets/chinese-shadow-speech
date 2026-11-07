from __future__ import annotations
import logging
import threading
from dataclasses import dataclass, replace
from typing import Any, Protocol
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


@dataclass(frozen=True)
class LetterEmissions:
    """The MMS letter log-probs an alignment computed on one take (T x letters, an inference-mode tensor), seconds
    per frame, and the letter model that computed them: the sound check reuses them only from its own model."""
    logp: Any
    frame_s: float
    source: object


def align_keeping_emissions(aligner: Aligner, wav: np.ndarray, sr: int,
                            text: str) -> tuple[list[Span], LetterEmissions | None]:
    """`aligner.align`, keeping the letter emissions it computed (None from an aligner without them), so the sound
    check on the same take need not run the model again."""
    f = getattr(aligner, "align_emissions", None)
    return f(wav, sr, text) if f is not None else (aligner.align(wav, sr, text), None)


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

    def align_emissions(self, wav: np.ndarray, sr: int, text: str) -> tuple[list[Span], LetterEmissions | None]:
        with self._lock:
            spans, em = align_keeping_emissions(self.inner, wav, sr, text)
        # the sound detector holds this wrapper as its letter model, so the emissions are this wrapper's
        return spans, None if em is None else replace(em, source=self)

    # Wrong-sound detection (Phase 3a) reads the MMS letter posteriors; same model, same lock.
    @property
    def blank(self) -> int:
        with self._lock:
            return self.inner.blank

    def emissions(self, wav: np.ndarray, sr: int):
        with self._lock:
            return self.inner.emissions(wav, sr)

    def letter_ids(self, syllable: str) -> list[int]:
        with self._lock:
            return self.inner.letter_ids(syllable)


def speech_chars(text: str) -> list[str]:
    return [c for c in text if not is_punct(c)]


def toneless_pinyin(hans: str | list[str]) -> list[str]:
    """Toneless pinyin, lower case, ü written v (as in a syllable's `pinyin_toneless`). A string is romanised with
    word context; a list, item by item."""
    return [p.lower().replace("ü", "v") for p in lazy_pinyin(hans, style=Style.NORMAL)]


def romanise_for_mms(text: str) -> list[str]:
    return ["".join(ch for ch in p.replace("v", "u") if "a" <= ch <= "z") or "a"
            for p in toneless_pinyin(speech_chars(text))]


class FakeAligner:
    def align(self, wav: np.ndarray, sr: int, text: str) -> list[Span]:
        chars = speech_chars(text)
        dur = len(wav) / sr
        n = max(len(chars), 1)
        return [Span(c, i * dur / n, (i + 1) * dur / n, 1.0) for i, c in enumerate(chars)]


def _mms_model(bundle):
    """bundle.get_model(with_star=False) without the random fp32 copy: the architecture is built on the meta device
    and takes the downloaded weights as they are (peak: one copy of the weights, not two). Falls back to get_model
    if torchaudio's helpers look different or leave a meta tensor behind. A failed download raises as it always did."""
    import torch
    try:
        from torchaudio.pipelines._wav2vec2 import utils
        helpers = (utils._get_model, utils._get_state_dict, utils._extend_model,
                   bundle._model_type, bundle._params, bundle._path, bundle._remove_aux_axis, bundle._normalize_waveform)
    except (ImportError, AttributeError):
        log.warning("torchaudio's loader helpers are not as expected; loading the MMS aligner with get_model")
        return bundle.get_model(with_star=False)
    get_model, get_state_dict, extend_model, mtype, params, path, remove_axis, normalize = helpers
    state_dict = get_state_dict(path, None, remove_axis)             # the download: errors are the caller's
    try:
        with torch.device("meta"):
            model = get_model(mtype, params)
        model.load_state_dict(state_dict, assign=True)
        model = extend_model(model, normalize_waveform=normalize, apply_log_softmax=True, append_star=False).eval()
        if any(t.is_meta for t in [*model.parameters(), *model.buffers()]):
            raise RuntimeError("a meta tensor is left")
        return model
    except Exception:
        log.warning("building the MMS aligner on the meta device failed; using get_model", exc_info=True)
        return bundle.get_model(with_star=False)


class MmsAligner:
    def __init__(self, device: str, int8: bool = False):
        self.device, self.int8 = device, int8
        self._bundle = self._model = self._tok = self._al = None
        self._dict: dict[str, int] | None = None

    def _letters(self) -> dict[str, int]:
        # the letter dictionary needs no model weights, so letter_ids/blank never load the model
        if self._dict is None:
            import torchaudio
            self._dict = torchaudio.pipelines.MMS_FA.get_dict(star=None)
        return self._dict

    @property
    def blank(self) -> int:
        return self._letters()["-"]       # 0 for MMS_FA, the blank the 3a spike used

    def letter_ids(self, syllable: str) -> list[int]:
        """Letter ids of a toneless syllable as the 3a spike spelled it (ü/v as u; nothing spellable gives "a")."""
        d = self._letters()
        return [d[c] for c in syllable.replace("v", "u") if c in d] or [d["a"]]

    def _load(self):
        if self._model is None:
            import torchaudio
            from shadow.hf import model_load_lock
            with model_load_lock:
                self._bundle = torchaudio.pipelines.MMS_FA
                if self.int8:
                    from shadow.quant import cached_int8, quantize_linear
                    model = cached_int8(f"mms_fa-torchaudio{torchaudio.__version__}", lambda: quantize_linear(_mms_model(self._bundle).eval()))
                else:
                    model = _mms_model(self._bundle)
                model = model.to(self.device).eval()
                self._model = model
                self._tok = self._bundle.get_tokenizer()
                self._al = self._bundle.get_aligner()
        return self._model

    def emissions(self, wav: np.ndarray, sr: int):
        """Frame letter log-probs (T x letters, an inference-mode tensor) and seconds per frame, as align uses them.
        The bundle's model already ends in log_softmax; the 3a spike scored GOP on this raw output, so add none."""
        import torch
        model = self._load()
        x = torch.from_numpy(wav).float().unsqueeze(0).to(self.device)
        if sr != self._bundle.sample_rate:
            import torchaudio.functional as F
            x = F.resample(x, sr, self._bundle.sample_rate)
        with torch.inference_mode():
            emission, _ = model(x)
        return emission[0], x.size(1) / emission.size(1) / self._bundle.sample_rate

    def align(self, wav: np.ndarray, sr: int, text: str) -> list[Span]:
        return self.align_emissions(wav, sr, text)[0]

    def align_emissions(self, wav: np.ndarray, sr: int, text: str) -> tuple[list[Span], LetterEmissions | None]:
        chars = speech_chars(text)
        if not chars:
            return [], None
        words = romanise_for_mms(text)
        emission, ratio = self.emissions(wav, sr)
        token_spans = self._al(emission, self._tok(words))
        out: list[Span] = []
        for ch, spans in zip(chars, token_spans, strict=True):
            out.append(Span(ch, spans[0].start * ratio, spans[-1].end * ratio,
                            float(sum(s.score for s in spans) / len(spans))))
        return out, LetterEmissions(emission, ratio, self)


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
            from shadow.hf import guarded_import, model_load_lock

            def _import_qwen():
                from qwen_asr import Qwen3ForcedAligner
                return Qwen3ForcedAligner
            Qwen3ForcedAligner = guarded_import(_import_qwen)
            with model_load_lock:
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


def make_aligner(name: str, device: str, int8: bool = False) -> Aligner:
    if name == "qwen3_fa":
        return Qwen3Aligner(device)
    if name == "mms_fa":
        return MmsAligner(device, int8)
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
