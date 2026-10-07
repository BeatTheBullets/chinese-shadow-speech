from __future__ import annotations
import html
import re
from dataclasses import dataclass
from opencc import OpenCC

_t2s = OpenCC("t2s")

PUNCT = frozenset("，。！？；：、“”‘’（）《》〈〉【】…—·,.!?;:()\"'[]<>-~～ 　\n\t\u300c\u300d\u300e\u300f")


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


def _drop_rolling_repeats(cues: list[list[str]]) -> list[list[str]]:
    """Lines per cue with rolling-caption repeats removed. yt-dlp auto-captions repeat each line as the first line
    of the next cue (`A\nB` → `B\nC`, often with a brief single-line `B` cue between). When a file rolls (some
    cue of two or more lines starts with the previous cue's last line), each cue's first line is dropped when it
    repeats the previous cue's last line. Files that do not roll are returned unchanged."""
    pairs = list(zip(cues, cues[1:]))
    if not any(len(cur) > 1 and prev and cur[0] == prev[-1] for prev, cur in pairs):
        return cues
    return cues[:1] + [cur[1:] if prev and cur and cur[0] == prev[-1] else cur for prev, cur in pairs]


def parse_subtitles(content: str, filename: str) -> list[Cue]:
    name = filename.lower()
    if name.endswith(".srt") or name.endswith(".vtt"):
        # WebVTT ends a block only at an empty line: yt-dlp auto-captions put whitespace-only lines inside cues
        sep = r"\n\n+" if name.endswith(".vtt") else r"\n\s*\n"
        timed: list[tuple[str, str, list[str]]] = []
        for block in re.split(sep, content.strip().replace("\r", "")):
            lines = [ln for ln in block.split("\n") if ln.strip()]
            if not lines or lines[0].upper().startswith("WEBVTT") or lines[0].upper().startswith("NOTE"):
                continue
            if "-->" not in lines[0] and len(lines) > 1 and "-->" in lines[1]:
                lines = lines[1:]
            if "-->" not in lines[0]:
                continue
            a, b = lines[0].split("-->")
            timed.append((a, b, [t for t in (to_simplified(strip_html(ln)) for ln in lines[1:]) if t]))
        texts = _drop_rolling_repeats([t for _, _, t in timed])
        return [Cue(_ts(a), _ts(b), " ".join(t)) for (a, b, _), t in zip(timed, texts) if t]
    return [Cue(-1, -1, to_simplified(strip_html(ln))) for ln in content.splitlines() if ln.strip()]
