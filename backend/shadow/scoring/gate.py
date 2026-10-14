"""Quality gate (Phase 2 spec §1 step 2): takes that cannot be scored meaningfully come back as warnings instead."""
from __future__ import annotations
import itertools
import numpy as np
from rapidfuzz.distance import Levenshtein
from shadow.config import ScoringCfg
from shadow.ingest.align import Span, toneless_pinyin
from shadow.ingest.text import is_hanzi, is_punct


def level_dbfs(wav: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(np.asarray(wav, dtype=np.float64) ** 2)) + 1e-12)) if len(wav) else -240.0


def clipped_ratio(wav: np.ndarray) -> float:
    return float(np.mean(np.abs(wav) >= 0.999)) if len(wav) else 0.0


def pre_gate(wav: np.ndarray, sr: int, ref_speech_s: float, cfg: ScoringCfg) -> list[str]:
    """Checks on the trimmed take before any alignment or pitch call (parselmouth raises on very short sounds)."""
    out = []
    if len(wav) / sr < max(cfg.min_duration_ratio * ref_speech_s, 0.15):
        out.append("too_short")
    if level_dbfs(wav) < cfg.min_rms_dbfs:
        out.append("too_quiet")
    if clipped_ratio(wav) > cfg.max_clipped:
        out.append("clipped")
    return out


def _is_latin(c: str) -> bool:
    return c.isascii() and c.isalpha()


def text_similarity(syllables: list[dict], heard: str) -> float:
    """How closely what the recogniser heard matches the sentence, 0..1, over toneless syllables (non-hanzi skipped
    on both sides). Toneless on purpose: a wrong tone can make the recogniser write a homophone, and that is the
    tone scorer's business, not other words. The sentence's pinyin comes from ingest (jieba word context), the heard
    side's from pypinyin over the heard hanzi alone, so a rare polyphone or a digit can differ between the two.
    A mostly Latin transcript (a name the recogniser spelt in English: 丽丽 heard as "lily") is also compared letter
    by letter, and the higher similarity counts."""
    expected = [s["pinyin_toneless"].lower() for s in syllables if s["tone"] >= 0]
    got = toneless_pinyin("".join(c for c in heard if is_hanzi(c)))
    sim = float(Levenshtein.normalized_similarity(expected, got))
    chars = [c for c in heard if not is_punct(c) and not c.isspace()]
    if chars and 2 * sum(map(_is_latin, chars)) >= len(chars):
        runs = itertools.groupby(heard, key=lambda c: "han" if is_hanzi(c) else "latin" if _is_latin(c) else None)
        letters = "".join("".join(toneless_pinyin("".join(r))) if k == "han" else "".join(r).lower()
                          for k, r in runs if k)
        sim = max(sim, float(Levenshtein.normalized_similarity("".join(expected), letters)))
    return sim


def align_gate(spans: list[Span], cfg: ScoringCfg) -> list[str]:
    """A garbled take aligns with low confidence (a different sentence often does not: `text_similarity` checks)."""
    if spans and float(np.mean([s.conf for s in spans])) < cfg.min_align_conf:
        return ["wrong_or_unclear"]
    return []
