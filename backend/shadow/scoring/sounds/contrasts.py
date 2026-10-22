"""Contrast partners, confusion directions and labels for wrong-sound detection (ported from the 3a spike).

Everything here is pure and table-driven: the detector, the stats and the drills all key off the same direction
strings ("ch>c" = expected ch, heard c), so the tables below are the single source of truth."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pypinyin.contrib.tone_convert import to_tone

_INVENTORY = Path(__file__).resolve().parent.parent / "models" / "syllables_v1.json"
# Inventory syllables no character in B's (char-CTC) vocab reads as, frozen offline from the pinned tokenizer with
# group_matrix: such a syllable has no column of its own, so it is never an alternative and a direction towards it is
# never checked (spec §2.1). tests/test_sounds_real.py re-derives it from the loaded model.
_B_SILENT = Path(__file__).resolve().parent.parent / "models" / "b_silent_v1.json"

# Longest first so "zh" wins over "z"; y/w count as initials only so UV pairs like yu/wu split consistently.
INITIALS = ["zh", "ch", "sh", "b", "p", "m", "f", "d", "t", "n", "l", "g", "k", "h", "j", "q", "x", "r", "z", "c", "s",
            "y", "w"]
INIT_PAIRS = {"zh/z": ("zh", "z"), "ch/c": ("ch", "c"), "sh/s": ("sh", "s"), "r/l": ("r", "l"), "f/h": ("f", "h")}
NNG = [("an", "ang"), ("en", "eng"), ("in", "ing"), ("ian", "iang"), ("uan", "uang")]
UV = [("lv", "lu"), ("nv", "nu"), ("yu", "wu")]
VOWEL = [("ai", "ei"), ("ao", "ou"), ("ou", "uo"), ("an", "en"), ("ang", "eng")]

DIRECTIONS: tuple[str, ...] = (
    "zh>z", "z>zh", "ch>c", "c>ch", "sh>s", "s>sh", "r>l", "l>r", "f>h", "h>f",
    "ng>n", "n>ng",
    "ü>u", "u>ü",
    "ai>ei", "ei>ai", "ao>ou", "ou>ao", "ou>uo", "uo>ou", "an>en", "en>an", "ang>eng", "eng>ang",
)
_UV_EXPECTED_U_UMLAUT = {"lv", "nv", "yu"}


@lru_cache(maxsize=1)
def inventory() -> frozenset[str]:
    return frozenset(json.loads(_INVENTORY.read_text()))


@lru_cache(maxsize=1)
def b_silent() -> frozenset[str]:
    return frozenset(json.loads(_B_SILENT.read_text()))


def _split(s: str) -> tuple[str, str]:
    for i in INITIALS:
        if s.startswith(i) and len(s) > len(i):
            return i, s[len(i):]
    return "", s


def partners(s: str) -> list[tuple[str, str]]:
    """(partner syllable, contrast name) for every contrast partner of `s` that is a valid syllable."""
    out: list[tuple[str, str]] = []
    ini, fin = _split(s)
    for name, (a, b) in INIT_PAIRS.items():
        for x, y in ((a, b), (b, a)):
            if ini == x:
                out.append((y + fin, name))
    for x, y in NNG:
        for p, q in ((x, y), (y, x)):
            if fin == p:
                out.append((ini + q, "n/ng"))
    for x, y in UV:
        for p, q in ((x, y), (y, x)):
            if s == p:
                out.append((q, "ü/u"))
    for x, y in VOWEL:
        for p, q in ((x, y), (y, x)):
            if fin == p:
                out.append((ini + q, "vowel"))
    inv = inventory()
    seen: set[str] = set()
    res = []
    for p, n in out:
        if p in inv and p != s and p not in seen:
            seen.add(p)
            res.append((p, n))
    return res


def direction(expected: str, heard: str) -> str | None:
    """Direction key for expected said as heard, or None when they are not contrast partners."""
    name = next((n for p, n in partners(expected) if p == heard), None)
    if name is None:
        return None
    (ei, ef), (hi, hf) = _split(expected), _split(heard)
    if name == "n/ng":
        return "ng>n" if ef.endswith("ng") else "n>ng"
    if name == "ü/u":
        return "ü>u" if expected in _UV_EXPECTED_U_UMLAUT else "u>ü"
    if name == "vowel":
        return f"{ef}>{hf}"
    return f"{ei}>{hi}"


def directions_of(s: str) -> set[str]:
    return {d for p, _ in partners(s) if (d := direction(s, p))}


def checkable_directions_of(s: str) -> set[str]:
    """The directions the detector can actually check on `s`: those whose partner has characters in B. A chance or a
    drill target is a syllable that can be checked (spec §4/§5); ding's only partner din has none, so ding has none."""
    silent = b_silent()
    return {d for p, _ in partners(s) if p not in silent and (d := direction(s, p))}


def _group(key: str) -> str:
    return "nng" if key in ("ng>n", "n>ng") else "uv" if key in ("ü>u", "u>ü") else ""


def direction_label(key: str) -> str:
    a, b = key.split(">")
    if _group(key) == "nng":
        a, b = "-" + a, "-" + b
    return f"{a} said as {b}"


def drill_label(key: str) -> str:
    a, b = key.split(">")
    if _group(key) == "nng":
        a, b = "-" + a, "-" + b
    return f"{a} (not {b})"


def heard_pinyin(toneless: str, tone: int) -> str:
    """Toned pinyin for display; tone <= 0 (neutral/unknown) gives the plain syllable, v shown as ü."""
    if tone <= 0:
        return toneless.replace("v", "ü")
    return to_tone(f"{toneless}{tone}")
