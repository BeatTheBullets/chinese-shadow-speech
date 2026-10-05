from __future__ import annotations
import html
import re
from dataclasses import dataclass
from opencc import OpenCC

_t2s = OpenCC("t2s")

PUNCT = frozenset("，。！？；：、""''（）《》〈〉【】…—·,.!?;:()\"'[]<>-~～ 　\n\t")


def to_simplified(s: str) -> str:
    return _t2s.convert(s)


def is_punct(ch: str) -> bool:
    return ch in PUNCT


def strip_punct(s: str) -> str:
    return "".join(ch for ch in s if not is_punct(ch))


_TAG = re.compile(r"<[^>]+>")


def strip_html(s: str) -> str:
    s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
    s = _TAG.sub("", s)
    s = html.unescape(s).replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip()


@dataclass
class Cue:
    start: float
    end: float
    text: str


_TIME = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{3})")


def _ts(s: str) -> float:
    m = _TIME.search(s)
    if not m:
        raise ValueError(f"bad timestamp: {s}")
    h, mi, se, ms = m.groups()
    return int(h or 0) * 3600 + int(mi) * 60 + int(se) + int(ms) / 1000


def parse_subtitles(content: str, filename: str) -> list[Cue]:
    name = filename.lower()
    if name.endswith(".srt") or name.endswith(".vtt"):
        cues: list[Cue] = []
        for block in re.split(r"\n\s*\n", content.strip().replace("\r", "")):
            lines = [ln for ln in block.split("\n") if ln.strip()]
            if not lines or lines[0].upper().startswith("WEBVTT") or lines[0].upper().startswith("NOTE"):
                continue
            if "-->" not in lines[0] and len(lines) > 1 and "-->" in lines[1]:
                lines = lines[1:]
            if "-->" not in lines[0]:
                continue
            a, b = lines[0].split("-->")
            text = to_simplified(strip_html(" ".join(lines[1:])))
            if text:
                cues.append(Cue(_ts(a), _ts(b), text))
        return cues
    return [Cue(-1, -1, to_simplified(strip_html(ln))) for ln in content.splitlines() if ln.strip()]
