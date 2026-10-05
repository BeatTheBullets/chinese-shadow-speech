from __future__ import annotations
from datetime import datetime
from typing import Any
from pydantic import BaseModel


class JobOut(BaseModel):
    id: str
    stage: str
    fraction: float
    status: str
    error: str | None
    lesson_id: int | None


class SegmentOut(BaseModel):
    id: int
    lesson_id: int
    idx: int
    start_s: float
    end_s: float
    text: str
    translation: str | None
    words_json: list[dict[str, Any]] | None
    ref_alignment_json: list[dict[str, Any]] | None
    difficulty_flag: bool
    anki_note_id: int | None
    last_score: float | None = None
    best_score: float | None = None
    attempts: int = 0


class LessonOut(BaseModel):
    id: int
    title: str
    speaker: str
    source_type: str
    source_ref: str
    duration_s: float
    created_at: datetime
    status: str
    error: str | None
    segment_count: int = 0
    practised_count: int = 0
    mean_last_score: float | None = None


class LessonDetail(LessonOut):
    segments: list[SegmentOut]


class AttemptOut(BaseModel):
    id: int
    segment_id: int
    session_id: int | None
    created_at: datetime
    mode: str
    duration_s: float
    score_json: dict[str, Any] | None


class SessionOut(BaseModel):
    id: int
    lesson_id: int
    mode: str
    started_at: datetime
    ended_at: datetime | None
    attempts_count: int
