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


_HANZI = re.compile("[㐀-䶿一-鿿豈-﫿\U00020000-\U0002ebef]")


def is_hanzi(ch: str) -> bool:
    return bool(_HANZI.match(ch))


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


# A file rolls only when at least this many cues, and at least half of its multi-line cues, echo the previous cue.
MIN_ROLLING_ECHOES = 3


def _drop_rolling_repeats(cues: list[list[str]]) -> list[list[str]]:
    """Lines per cue with rolling-caption repeats removed. yt-dlp auto-captions repeat each line as the first line
    of the next cue (`A\nB` → `B\nC`, often with a brief single-line `B` cue between). A file rolls when cues of
    two or more lines that start with the previous cue's last line (echoes) number at least `MIN_ROLLING_ECHOES`
    and make up at least half of its multi-line cues; then each cue's first line is dropped when it repeats the
    previous cue's last line. Other files, including ones where a speaker happens to repeat a line, are returned
    unchanged."""
    pairs = list(zip(cues, cues[1:]))
    multi_line = [(prev, cur) for prev, cur in pairs if len(cur) > 1]
    echoes = sum(1 for prev, cur in multi_line if prev and cur[0] == prev[-1])
    if echoes < MIN_ROLLING_ECHOES or 2 * echoes < len(multi_line):
        return cues
    return cues[:1] + [cur[1:] if prev and cur and cur[0] == prev[-1] else cur for prev, cur in pairs]


def parse_subtitles(content: str, filename: str) -> list[Cue]:
    name = filename.lower()
    if name.endswith(".srt") or name.endswith(".vtt"):
        # WebVTT ends a block only at an empty line: yt-dlp auto-captions put whitespace-only lines inside cues
        sep = r"\n\n+" if name.endswith(".vtt") else r"\n\s*\n"
        timed: list[tuple[str, str, list[str]]] = []
        for block in re.split(sep, content.strip().replace("\r", "")):
            in_cue = False          # lines before a block's first timing line: header, NOTE, cue identifier
            # The text line just added is a cue identifier if a timing line follows it: when it came after a
            # whitespace-only line (VTT separated by such lines) or is a number (SRT index without blank lines).
            identifier = prev_blank = False
            for ln in block.split("\n"):
                if "-->" in ln:     # a timing line starts a new cue, even without an empty line before it
                    if identifier:
                        timed[-1][2].pop()
                    a, b = ln.split("-->")
                    timed.append((a, b, []))
                    in_cue, identifier = True, False
                elif in_cue and (text := to_simplified(strip_html(ln))):
                    timed[-1][2].append(text)
                    identifier = prev_blank or ln.strip().isdigit()
                else:
                    identifier = False
                prev_blank = not ln.strip()
        texts = _drop_rolling_repeats([t for _, _, t in timed])
        return [Cue(_ts(a), _ts(b), " ".join(t)) for (a, b, _), t in zip(timed, texts) if t]
    return [Cue(-1, -1, to_simplified(strip_html(ln))) for ln in content.splitlines() if ln.strip()]
