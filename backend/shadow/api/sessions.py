from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session
from shadow.schemas import SessionOut
from shadow.store.db import get_session
from shadow.store.models import PracticeSession, Lesson

router = APIRouter()

MODES = {"echo", "chorus", "flow", "guided"}


class SessionIn(BaseModel):
    lesson_id: int
    mode: str


class SessionPatch(BaseModel):
    ended: bool = False


@router.post("/sessions", response_model=SessionOut, status_code=201)
def create_session(body: SessionIn, db: Session = Depends(get_session)):
    if db.get(Lesson, body.lesson_id) is None:
        raise HTTPException(404, "lesson not found")
    if body.mode not in MODES:
        raise HTTPException(400, "bad mode")
    s = PracticeSession(lesson_id=body.lesson_id, mode=body.mode)
    db.add(s); db.commit(); db.refresh(s)
    return s


@router.patch("/sessions/{session_id}", response_model=SessionOut)
def patch_session(session_id: int, body: SessionPatch, db: Session = Depends(get_session)):
    s = db.get(PracticeSession, session_id)
    if s is None:
        raise HTTPException(404, "session not found")
    if body.ended:
        s.ended_at = datetime.now(timezone.utc)
    db.add(s); db.commit(); db.refresh(s)
    return s
