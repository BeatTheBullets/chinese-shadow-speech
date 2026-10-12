from __future__ import annotations
import itertools
import os
import re
import uuid
from pathlib import Path
import jieba
from pypinyin import lazy_pinyin, Style
from shadow.ingest import audio
from shadow.ingest.llm import LLM
from shadow.ingest.text import is_hanzi, is_punct, strip_punct
from shadow.store.files import FileLayout

jieba.setLogLevel(60)
_DIGIT = re.compile(r"\d")
NON_HANZI_TONE = -1


def _tone_of(tone3: str) -> int:
    m = _DIGIT.search(tone3)
    t = int(m.group()) if m else 5
    return 0 if t == 5 else t


def _syllables_of_word(word: str) -> list[dict]:
    """One entry per non-punctuation character of `word`. Contiguous hanzi runs are romanised together
    (so polyphones and tone sandhi see word context); any other character (digit, Latin letter, symbol)
    becomes its own entry with pinyin = the character and tone = -1."""
    out: list[dict] = []
    for is_han, grp in itertools.groupby((c for c in word if not is_punct(c)), key=is_hanzi):
        run = "".join(grp)
        if not is_han:
            out.extend({"ch": c, "pinyin": c, "pinyin_toneless": c, "tone": NON_HANZI_TONE} for c in run)
            continue
        tone = lazy_pinyin(run, style=Style.TONE, tone_sandhi=True, neutral_tone_with_five=True)
        tone3 = lazy_pinyin(run, style=Style.TONE3, tone_sandhi=True, neutral_tone_with_five=True)
        if not len(tone) == len(tone3) == len(run):
            raise ValueError(f"pinyin count mismatch for {run!r}: {tone}")
        for ch, p, p3 in zip(run, tone, tone3):
            if p == ch:                      # pypinyin has no reading for this character
                out.append({"ch": ch, "pinyin": ch, "pinyin_toneless": ch, "tone": NON_HANZI_TONE})
            else:
                out.append({"ch": ch, "pinyin": p,
                            "pinyin_toneless": _DIGIT.sub("", p3).replace("ü", "v"),
                            "tone": _tone_of(p3)})
    return out


def words_for(text: str) -> list[dict]:
    out: list[dict] = []
    pos = 0
    for word in jieba.lcut(text):
        a, b = pos, pos + len(word) - 1
        pos += len(word)
        if not strip_punct(word):
            continue
        syllables = _syllables_of_word(word)
        out.append({
            "word": word,
            "pinyin": "".join(s["pinyin"] for s in syllables),
            "tones": [s["tone"] for s in syllables],
            "char_from": a, "char_to": b,
            "syllables": syllables,
        })
    return out


def syllables_for(text: str) -> list[dict]:
    """One syllable per non-punctuation character of `text`, in order (matches the aligner's spans)."""
    chars = [c for c in text if not is_punct(c)]
    out = [s for w in words_for(text) for s in w["syllables"]]
    if [s["ch"] for s in out] != chars:
        raise ValueError(f"syllables do not match speech characters for {text!r}")
    return out


def translate_all(llm: LLM, texts: list[str], batch: int = 20) -> list[str]:
    out: list[str] = []
    for i in range(0, len(texts), batch):
        out.extend(llm.translate(texts[i:i + batch]))
    return out


def make_clips(files: FileLayout, lesson_id: int, idx: int, source_wav: Path, start_s: float, end_s: float) -> tuple[Path, Path]:
    """Cut and encode under temporary names, then move both into place: a failed cut or encode (e.g. during an
    edit's re-enrich) leaves the segment's existing clips as they were."""
    wav, opus = files.clip_wav(lesson_id, idx), files.clip_opus(lesson_id, idx)
    tag = uuid.uuid4().hex[:8]
    tmp_wav, tmp_opus = wav.with_name(f"{idx}.{tag}.part.wav"), opus.with_name(f"{idx}.{tag}.part.opus")
    try:
        audio.cut(source_wav, tmp_wav, start_s, end_s)
        audio.encode_opus(tmp_wav, tmp_opus)
        os.replace(tmp_wav, wav)
        os.replace(tmp_opus, opus)
    finally:
        tmp_wav.unlink(missing_ok=True)
        tmp_opus.unlink(missing_ok=True)
    return wav, opus
