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


def chars_with_speech_times(text: str, speech_times: list[tuple[float, float]], start: float) -> list[TimedChar]:
    """Lay `speech_times` over the non-punctuation chars of `text`; punctuation gets a zero-length
    time at the end of the previous speech char (or `start`). Needs one time per speech char."""
    out: list[TimedChar] = []
    times = iter(speech_times)
    last_end = start
    for ch in text:
        if is_punct(ch):
            out.append(TimedChar(ch, last_end, last_end))
        else:
            s, e = next(times)
            out.append(TimedChar(ch, s, e))
            last_end = e
    return out


def chars_with_interpolated_times(text: str, start: float, end: float) -> list[TimedChar]:
    count = sum(1 for ch in text if not is_punct(ch))
    n = max(count, 1)
    step = (end - start) / n
    speech_times = [(start + k * step, end if k == n - 1 else start + (k + 1) * step) for k in range(count)]
    return chars_with_speech_times(text, speech_times, start)


def append_segment(tr: Transcript, chars: list[TimedChar]) -> bool:
    """Append `chars` to `tr` as one new segment. Returns False (and does nothing) if `chars` is empty."""
    if not chars:
        return False
    a = len(tr.chars)
    tr.chars.extend(chars)
    tr.segments.append((a, len(tr.chars) - 1))
    return True


def transcript_from_cues(cues: list[Cue]) -> Transcript:
    ordered = sorted(cues, key=lambda c: c.start)
    tr = Transcript()
    floor = 0.0
    for cue in ordered:
        start = max(cue.start, floor)
        end = max(cue.end, start)
        if append_segment(tr, chars_with_interpolated_times(cue.text, start, end)):
            floor = max(floor, tr.chars[-1].end)
    return tr
