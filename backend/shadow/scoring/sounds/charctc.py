"""Method B model: the Chinese char-CTC wav2vec2 (spec §6). Its per-character posteriors are pooled into
toneless-syllable groups (a character counts for every reading pypinyin knows), so the detector can run CTC over
syllables. Ported from the 3a spike (method_b.py); the downstream thresholds were calibrated on this arithmetic."""
from __future__ import annotations
import logging
import threading
from typing import Protocol
import numpy as np

from shadow.memory import trim_heap

log = logging.getLogger(__name__)


def group_matrix(vocab: dict[str, int], size: int, blank: int, syllables: list[str]) -> np.ndarray:
    """size × (1+S): column 0 is blank, column i+1 the syllable syllables[i]. A single-hanzi token counts for every
    reading in `syllables`; other tokens (latin letters, specials) stay all-zero rows."""
    from pypinyin import pinyin, Style
    sid = {s: i + 1 for i, s in enumerate(syllables)}
    M = np.zeros((size, len(syllables) + 1), dtype=np.float32)
    M[blank, 0] = 1
    for ch, vid in vocab.items():
        if len(ch) == 1 and "一" <= ch <= "鿿":
            for r in pinyin(ch, style=Style.NORMAL, heteronym=True)[0]:
                r = r.lower().replace("ü", "v")
                if r in sid:
                    M[vid, sid[r]] = 1
    return M


class CharModel(Protocol):
    blank: int                            # blank's column in GROUP space: always 0 (CTC runs over the group log-probs)

    def group_logp(self, wav: np.ndarray, sr: int): ...   # torch.Tensor, T × (1+S)
    def sid(self, s: str) -> int | None: ...              # column of a syllable that has characters (alternatives)
    def column(self, s: str) -> int | None: ...           # column of any inventory syllable (the expected sequence)


class CharCtc:
    blank = 0

    def __init__(self, name: str, revision: str, device: str):
        self.name, self.revision, self.device = name, revision, device
        self._model = None
        self._Mt = None
        self._sid: dict[str, int] = {}
        self._col: dict[str, int] | None = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            from transformers import Wav2Vec2CTCTokenizer, Wav2Vec2ForCTC
            import torch
            from .contrasts import inventory
            model = Wav2Vec2ForCTC.from_pretrained(self.name, revision=self.revision, low_cpu_mem_usage=True)
            vocab = Wav2Vec2CTCTokenizer.from_pretrained(self.name, revision=self.revision).get_vocab()
            syls = sorted(inventory())
            M = group_matrix(vocab, model.config.vocab_size, model.config.pad_token_id, syls)
            self._sid = {s: i + 1 for i, s in enumerate(syls) if M[:, i + 1].sum() > 0}
            self._Mt = torch.from_numpy(M).to(self.device)
            self._model = model.to(self.device).eval()
        return self._model

    def warm_up(self) -> threading.Thread:
        """Load (first run: download) the model in a daemon thread; under the lock, so a take arriving meanwhile waits
        for this load instead of starting another. A failure is logged and the next take tries again."""
        def run():
            try:
                with self._lock:
                    self._load()
            except Exception:
                log.exception("warming up the char-CTC model %s failed", self.name)
            finally:
                trim_heap()
        t = threading.Thread(target=run, name="charctc-warm-up", daemon=True)
        t.start()
        return t

    def sid(self, s: str) -> int | None:
        with self._lock:
            self._load()
        return self._sid.get(s)

    def column(self, s: str) -> int | None:
        """Group column of any inventory syllable, with characters or not. The spike's expected sequence used it, so a
        syllable without characters sits in the sequence as its own all-zero column (log 1e-30), not as blank; only
        syllables outside the inventory map to blank. Needs no model: the columns are the sorted inventory."""
        if self._col is None:
            from .contrasts import inventory
            self._col = {x: i + 1 for i, x in enumerate(sorted(inventory()))}
        return self._col.get(s)

    def group_logp(self, wav: np.ndarray, sr: int):
        import torch
        import torchaudio.functional as AF
        with self._lock:
            model = self._load()
            x = torch.from_numpy(np.asarray(wav, np.float32))
            if sr != 16000:
                x = AF.resample(x, sr, 16000)
            x = ((x - x.mean()) / (x.std() + 1e-7)).unsqueeze(0).to(self.device)
            with torch.inference_mode():
                lg = model(x).logits[0].float()
                return (lg.softmax(-1) @ self._Mt).clamp_min(1e-30).log()
