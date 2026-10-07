from __future__ import annotations
from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select
from shadow.api.lessons import _segment_out
from shadow.schemas import SegmentOut
from shadow.store.db import get_session
from shadow.store.models import Attempt, Lesson, Segment

router = APIRouter()


class UnexportedOut(BaseModel):
    lesson_id: int
    lesson_title: str
    lesson_source_type: str
    lesson_source_ref: str
    last_attempt_at: datetime
    segment: SegmentOut


@router.get("/review/unexported", response_model=list[UnexportedOut])
def unexported(db: Session = Depends(get_session)):
    """Practised sentences (at least one attempt, any mode, Flow slices included) that have no Anki note, newest last
    attempt first (addendum §5.2): what a session-end export did not send, e.g. because Anki was closed."""
    last = func.max(Attempt.created_at)
    q = (select(Segment, Lesson, last).join(Attempt, Attempt.segment_id == Segment.id).join(Lesson, Lesson.id == Segment.lesson_id)
         .where(Segment.anki_note_id.is_(None)).group_by(Segment.id).order_by(last.desc(), Segment.id.desc()))
    return [UnexportedOut(lesson_id=lesson.id, lesson_title=lesson.title, lesson_source_type=lesson.source_type,
                          lesson_source_ref=lesson.source_ref, last_attempt_at=last_at, segment=_segment_out(db, seg))
            for seg, lesson, last_at in db.exec(q).all()]
