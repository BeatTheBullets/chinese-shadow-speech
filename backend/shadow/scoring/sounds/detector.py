"""Per-take wrong-sound detector (spec §2): MMS letters (A, windowed GOP on the take) and char-CTC syllable groups
(B, full-utterance GOP on take and reference) fused into a per-syllable ok/slip verdict and the syllable heard.

Ported from the 3a spike (method_a.py, method_b.py, evaluate.badness: A "win" abs, B "utt" delta); the fusion
constants were calibrated on exactly these sequences and alternatives, so they must not drift."""
from __future__ import annotations
import threading
from collections import OrderedDict
from typing import Protocol
import numpy as np

from shadow.config import SoundsCfg
from .charctc import CharModel
from .contrasts import heard_pinyin, inventory, partners
from .decide import decide
from .gop import utt_gops, win_gop

SKIP_STATUSES = ("missing", "unvoiced")      # nothing (or nothing voiced) was said, so there is no sound to judge
REF_CACHE = 64


class LetterModel(Protocol):
    blank: int

    def emissions(self, wav: np.ndarray, sr: int): ...   # (torch.Tensor T × letters, seconds per frame)
    def letter_ids(self, s: str) -> list[int]: ...


class Sounds(Protocol):
    def check(self, *, take: np.ndarray, sr: int, usr_win: list[tuple[float, float]], ref_wav: np.ndarray,
              ref_sr: int, ref_key: str, syllables: list[dict], statuses: list[str]) -> list[dict | None]: ...


class SoundDetector:
    def __init__(self, letters: LetterModel, chars: CharModel, cfg: SoundsCfg):
        self.letters, self.chars, self.cfg = letters, chars, cfg
        self._ref: OrderedDict[str, list[tuple[float, int] | None]] = OrderedDict()
        self._lock = threading.Lock()         # guards only the cache; the models lock themselves

    def check(self, *, take: np.ndarray, sr: int, usr_win: list[tuple[float, float]], ref_wav: np.ndarray,
              ref_sr: int, ref_key: str, syllables: list[dict], statuses: list[str]) -> list[dict | None]:
        """Per syllable: None (not checked) or {status, heard, heard_pinyin, z, rule}; heard only on a slip."""
        import torch
        syl = [s["pinyin_toneless"].lower() for s in syllables]
        inv = inventory()
        chars = self.chars
        part = [[p for p, _ in partners(s)] for s in syl]
        # B: a syllable B has no group for stays in the sequence as blank (the spike's `ids(s) or [0]`); only
        # partners B can say are alternatives, so heard is always one of these.
        seq_b = [[chars.sid(s) or 0] for s in syl]
        said_b = [[p for p in ps if chars.sid(p)] for ps in part]
        alts_b = [[[chars.sid(p)] for p in ps] for ps in said_b]
        judged = [statuses[i] not in SKIP_STATUSES and syllables[i]["tone"] >= 0 and s in inv
                  for i, s in enumerate(syl)]
        # without a B alternative decide() has no verdict, so a take with none runs no model at all
        if not any(j and alts_b[i] for i, j in enumerate(judged)):
            return [None] * len(syl)
        with torch.inference_mode():          # model outputs are inference-mode tensors
            ref = self._ref_gops(ref_key, ref_wav, ref_sr, seq_b, alts_b)
            # each alternative swaps one syllable only, so dropping the unjudged ones' alternatives changes nothing
            usr = utt_gops(chars.group_logp(take, sr), chars.blank, seq_b,
                           [a if judged[i] else [] for i, a in enumerate(alts_b)])
            bad_b = [r[0] - u[0] if j and u is not None and r is not None else None
                     for j, u, r in zip(judged, usr, ref)]
            bad_a: list[float | None] = [None] * len(syl)
            if any(b is not None for b in bad_b):
                logp, frame_s = self.letters.emissions(take, sr)
                ids = self.letters.letter_ids
                for i, b in enumerate(bad_b):
                    if b is None:
                        continue
                    want = ids(syl[i])
                    alts = [list(a) for a in dict.fromkeys(tuple(ids(p)) for p in part[i]) if list(a) != want]
                    g = win_gop(logp, self.letters.blank, want, alts, usr_win[i], frame_s)
                    bad_a[i] = None if g is None else -g
        out: list[dict | None] = []
        for i in range(len(syl)):
            d = decide(bad_a[i], bad_b[i], self.cfg)
            if d is None:
                out.append(None)
                continue
            status, z, rule = d
            heard = said_b[i][usr[i][1]] if status == "slip" else None
            out.append({"status": status, "heard": heard,
                        "heard_pinyin": heard_pinyin(heard, syllables[i]["tone"]) if heard else None,
                        "z": float(z), "rule": rule})
        return out

    def _ref_gops(self, key: str, wav: np.ndarray, sr: int, seq: list[list[int]],
                  alts: list[list[list[int]]]) -> list[tuple[float, int] | None]:
        # the reference clip is the same for every take of a segment: one forward per clip (and text), not per take
        with self._lock:
            if key in self._ref:
                self._ref.move_to_end(key)
                return self._ref[key]
        res = utt_gops(self.chars.group_logp(wav, sr), self.chars.blank, seq, alts)
        with self._lock:
            self._ref[key] = res
            while len(self._ref) > REF_CACHE:
                self._ref.popitem(last=False)
        return res


class FakeSounds:
    """For scoring tests: returns the given results (all None by default), or raises when `error`."""
    def __init__(self, results: list[dict | None] | None = None, error: bool = False):
        self.results, self.error = results, error

    def check(self, *, take: np.ndarray, sr: int, usr_win: list[tuple[float, float]], ref_wav: np.ndarray,
              ref_sr: int, ref_key: str, syllables: list[dict], statuses: list[str]) -> list[dict | None]:
        if self.error:
            raise RuntimeError("sound check failed")
        return list(self.results) if self.results is not None else [None] * len(syllables)
