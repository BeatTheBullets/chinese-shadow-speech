from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field


def now() -> datetime:
    return datetime.now(timezone.utc)


class Lesson(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    speaker: str = ""
    source_type: str                      # upload | youtube | anki
    source_ref: str = ""
    duration_s: float = 0.0
    created_at: datetime = Field(default_factory=now)
    status: str = "queued"                # queued | processing | ready | error
    error: str | None = None
    meta_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))
    transcript_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class Segment(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    lesson_id: int = Field(foreign_key="lesson.id", index=True)
    idx: int
    start_s: float
    end_s: float
    char_from: int | None = None
    char_to: int | None = None
    text: str
    translation: str | None = None
    words_json: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))
    ref_alignment_json: list[dict[str, Any]] | None = Field(default=None, sa_column=Column(JSON))
    difficulty_flag: bool = False
    anki_note_id: int | None = None
    clip_wav_path: str | None = None
    clip_opus_path: str | None = None


class PracticeSession(SQLModel, table=True):
    __tablename__ = "session"
    id: int | None = Field(default=None, primary_key=True)
    lesson_id: int = Field(foreign_key="lesson.id", index=True)
    mode: str                              # echo | chorus | flow | guided
    started_at: datetime = Field(default_factory=now)
    ended_at: datetime | None = None
    attempts_count: int = 0


class Attempt(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    segment_id: int = Field(foreign_key="segment.id", index=True)
    session_id: int | None = Field(default=None, foreign_key="session.id")
    created_at: datetime = Field(default_factory=now)
    mode: str
    audio_path: str
    duration_s: float
    score_json: dict[str, Any] | None = Field(default=None, sa_column=Column(JSON))


class SyllableScore(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    attempt_id: int = Field(foreign_key="attempt.id", index=True)
    segment_id: int = Field(foreign_key="segment.id", index=True)
    idx: int
    ch: str
    pinyin_toneless: str = Field(index=True)
    tone: int
    prev_tone: int | None = None
    tone_score: float | None = None
    seg_score: float | None = None
    status: str
