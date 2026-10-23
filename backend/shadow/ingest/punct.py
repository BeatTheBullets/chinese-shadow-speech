"""Punctuation from the small sherpa-onnx CT-Transformer (int8, 72 MB, about 0.18 GB peak) instead of FunASR's ct-punc
(peaks above 5 GB). `punctuate_timed` punctuates a recogniser's unpunctuated text in chunks cut at its largest pauses,
so marks stay between the same timed characters."""
from __future__ import annotations
import hashlib
import logging
import os
import shutil
import tarfile
import tempfile
import threading
import urllib.request
from pathlib import Path
from typing import Protocol
from shadow.config import SegmentationCfg
from shadow.ingest.pauses import pause_ranges
from shadow.ingest.text import is_punct
from shadow.ingest.transcript import TimedChar

log = logging.getLogger(__name__)
CHUNK_CHARS = 150               # speech characters per call: the model is trained on sentences, not paragraphs
MODEL_FILE = "model.int8.onnx"
COMPLETE = ".complete"          # written last: a directory without it is a partial unpack


class Punctuator(Protocol):
    def punctuate(self, text: str) -> str: ...


def models_cache_dir() -> Path:
    env = os.environ.get("SHADOW_MODELS_DIR")
    return Path(env) if env else Path.home() / ".cache" / "shadow-speech" / "models"


class SherpaPunctuator:
    def __init__(self, model: str, url: str, sha256: str, cache_dir: Path, threads: int = 2):
        self.model, self.url, self.sha256, self.cache_dir, self.threads = model, url, sha256, Path(cache_dir), threads
        self._punct = None
        self._lock = threading.Lock()

    def _model_path(self) -> Path:
        """The unpacked model file. The first call downloads the tarball (to a file of its own), checks its SHA-256,
        unpacks it into a temporary directory next to the final one, writes `.complete` last and renames the directory
        into place: a killed run leaves only temporary leftovers, and two processes cannot trample each other."""
        final = self.cache_dir / self.model
        if (final / COMPLETE).exists():
            return next(final.rglob(MODEL_FILE))
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        log.info("downloading the punctuation model %s", self.url)
        with tempfile.NamedTemporaryFile(dir=self.cache_dir, suffix=".tar.bz2", delete=False) as f:
            tgz = Path(f.name)
            try:
                with urllib.request.urlopen(self.url, timeout=60) as resp:
                    while chunk := resp.read(1 << 20):
                        digest.update(chunk)
                        f.write(chunk)
            except BaseException:
                f.close()
                tgz.unlink(missing_ok=True)
                raise
        tmp = Path(tempfile.mkdtemp(dir=self.cache_dir, prefix=self.model + ".tmp-"))
        try:
            if digest.hexdigest() != self.sha256:
                raise RuntimeError(f"punctuation model checksum mismatch: got {digest.hexdigest()}, want {self.sha256}")
            with tarfile.open(tgz) as t:
                t.extractall(tmp, filter="data")
            if next(tmp.rglob(MODEL_FILE), None) is None:
                raise RuntimeError(f"the punctuation model tarball has no {MODEL_FILE}")
            (tmp / COMPLETE).write_text("")
            if final.exists() and not (final / COMPLETE).exists():
                shutil.rmtree(final, ignore_errors=True)         # a partial directory from an older version
            try:
                os.replace(tmp, final)
            except OSError:
                if not (final / COMPLETE).exists():            # not another process winning: a real failure
                    raise
        finally:
            tgz.unlink(missing_ok=True)
            shutil.rmtree(tmp, ignore_errors=True)               # gone after a rename; ours to discard otherwise
        return next(final.rglob(MODEL_FILE))

    def _load(self):
        if self._punct is None:
            from shadow.hf import guarded_import, model_load_lock

            def _import():
                import sherpa_onnx
                return sherpa_onnx
            sherpa_onnx = guarded_import(_import)
            path = self._model_path()
            with model_load_lock:
                cfg = sherpa_onnx.OfflinePunctuationConfig(model=sherpa_onnx.OfflinePunctuationModelConfig(
                    ct_transformer=str(path), num_threads=self.threads, provider="cpu"))
                self._punct = sherpa_onnx.OfflinePunctuation(cfg)
        return self._punct

    def punctuate(self, text: str) -> str:
        with self._lock:
            return self._load().add_punctuation(text)


def make_punctuator(models) -> SherpaPunctuator | None:
    """The punctuator `[models]` asks for: "sherpa" -> the small sherpa-onnx model; "pauses" -> None (sentences are
    cut at pauses)."""
    if models.punctuation == "sherpa":
        return SherpaPunctuator(models.punctuation_model, models.punctuation_url, models.punctuation_sha256,
                                models_cache_dir())
    if models.punctuation == "pauses":
        return None
    raise ValueError(f'models.punctuation must be "sherpa" or "pauses", not {models.punctuation!r}')


def _speech(s: str) -> str:
    return "".join(ch for ch in s if not is_punct(ch)).lower()


def _compact(s: str) -> str:
    """Whitespace out, except between two ASCII letters or digits (the words of a Latin phrase)."""
    out: list[str] = []
    pending = False
    for ch in s:
        if ch.isspace():
            pending = bool(out)
            continue
        if pending and out[-1].isascii() and out[-1].isalnum() and ch.isascii() and ch.isalnum():
            out.append(" ")
        pending = False
        out.append(ch)
    return "".join(out)


def _split_unpunctuated(chunk: str, chars: list[TimedChar], cfg: SegmentationCfg) -> str:
    """A chunk the model changed, kept as it was but cut at its pauses (each piece ends in 。) and always ended with
    a mark, so it never runs into the next chunk as one giant sentence."""
    text = _compact(chunk)
    pos = [k for k, ch in enumerate(text) if not is_punct(ch)]
    out = ""
    if len(pos) == len(chars):
        last = 0
        for _, b in pause_ranges(chars, cfg):
            out += text[last:pos[b] + 1]
            last = pos[b] + 1
            if not is_punct(out[-1:]):
                out += "。"
        out += text[last:]
    else:
        out = text
    return out if out[-1:] and is_punct(out[-1]) else out + "。"


def punctuate_timed(text: str, timestamps: list[list[int]], punctuator: Punctuator, cfg: SegmentationCfg) -> str:
    """`text` (a recogniser's unpunctuated output) with marks added. It is cut at its largest timestamp gaps into
    chunks of at most 150 speech characters, each punctuated alone and joined in order, so a mark never moves
    between timed characters. A chunk the model changed beyond its marks is kept as it was."""
    from shadow.ingest.asr import _speech_times             # asr imports this module
    times, _ = _speech_times(text, timestamps)
    pos = [k for k, ch in enumerate(text) if not is_punct(ch)]
    if not pos or len(pos) != len(times):
        return text
    chars = [TimedChar(text[p], a, b) for p, (a, b) in zip(pos, times)]
    ranges = pause_ranges(chars, cfg.model_copy(update={"pause_cut_s": 1e9, "max_chars": CHUNK_CHARS}))
    out = ""
    for a, b in ranges:
        chunk = _compact(text[pos[a]:pos[b] + 1])
        done = punctuator.punctuate(chunk)
        if _speech(done) != _speech(chunk):
            log.warning("the punctuation model changed its text; keeping a chunk of %d chars unpunctuated", b - a + 1)
            done = _split_unpunctuated(chunk, chars[a:b + 1], cfg)
        if out and out[-1].isascii() and out[-1].isalnum() and done[:1].isascii() and done[:1].isalnum():
            out += " "
        out += done
    return out
