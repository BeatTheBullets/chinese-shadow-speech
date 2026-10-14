"""AISHELL-3 transcripts for training the tone model (Phase 2 spec §4.1). Training only; the app never imports it."""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
from shadow.ingest.enrich import syllables_for

_LABEL = re.compile(r"([a-zü]+)([1-5])")


@dataclass
class Utterance:
    speaker: str
    wav: Path
    chars: list[str]
    toneless: list[str | None]
    tones: list[int | None]              # 0 neutral; None where the label is not a plain toned syllable (erhua etc.)


def parse_label(label: str) -> tuple[str, int] | None:
    m = _LABEL.fullmatch(label.lower())
    if not m:
        return None
    t = int(m.group(2))
    return m.group(1), 0 if t == 5 else t


def read_split(split_dir: Path) -> list[Utterance]:
    """`content.txt` lines: `SSB00050001.wav<TAB>广 guang3 州 zhou1 …` (character, pinyin pairs)."""
    out = []
    for line in (split_dir / "content.txt").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 3 or len(parts) % 2 == 0 or not parts[0].endswith(".wav"):
            continue
        name, toks = parts[0], parts[1:]
        labels = [parse_label(p) for p in toks[1::2]]
        spk = name[:7]
        out.append(Utterance(spk, split_dir / "wav" / spk / name, toks[0::2],
                             [lb[0] if lb else None for lb in labels], [lb[1] if lb else None for lb in labels]))
    return out


def realise(u: Utterance) -> list[int | None]:
    """Canonical labels → the tones a speaker produces (3-3, 一, 不 sandhi), from the same pypinyin call as enrich;
    a character whose syllable pypinyin reads differently keeps its label."""
    try:
        syl = syllables_for("".join(u.chars))
    except ValueError:
        return list(u.tones)
    return [s["tone"] if t is not None and s["pinyin_toneless"] == tl else t
            for s, t, tl in zip(syl, u.tones, u.toneless)]
