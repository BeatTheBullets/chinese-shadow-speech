from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Any
from shadow.ingest.text import Cue, is_punct


@dataclass
class TimedChar:
    c: str
    start: float
    end: float


@dataclass
class Transcript:
    chars: list[TimedChar] = field(default_factory=list)
    segments: list[tuple[int, int]] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "".join(ch.c for ch in self.chars)

    def to_json(self) -> dict[str, Any]:
        return {"chars": [asdict(c) for c in self.chars], "segments": [list(s) for s in self.segments]}

    @classmethod
    def from_json(cls, d: dict[str, Any]) -> "Transcript":
        return cls([TimedChar(**c) for c in d["chars"]], [tuple(s) for s in d["segments"]])


def chars_with_interpolated_times(text: str, start: float, end: float) -> list[TimedChar]:
    speech = [i for i, ch in enumerate(text) if not is_punct(ch)]
    n = max(len(speech), 1)
    step = (end - start) / n
    out: list[TimedChar] = []
    k = 0
    last_end = start
    for i, ch in enumerate(text):
        if is_punct(ch):
            out.append(TimedChar(ch, last_end, last_end))
        else:
            s = start + k * step
            e = end if k == n - 1 else start + (k + 1) * step
            out.append(TimedChar(ch, s, e))
            last_end = e
            k += 1
    return out


def transcript_from_cues(cues: list[Cue]) -> Transcript:
    ordered = sorted(cues, key=lambda c: c.start)
    tr = Transcript()
    floor = 0.0
    for cue in ordered:
        start = max(cue.start, floor)
        end = max(cue.end, start)
        chars = chars_with_interpolated_times(cue.text, start, end)
        if not chars:
            continue
        a = len(tr.chars)
        tr.chars.extend(chars)
        tr.segments.append((a, len(tr.chars) - 1))
        floor = max(floor, tr.chars[-1].end)
    return tr
