from __future__ import annotations
import subprocess
import uuid
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select
from shadow.api.sessions import MODES
from shadow.ingest import audio
from shadow.schemas import AttemptOut
from shadow.scoring import score_attempt
from shadow.store.db import get_session
from shadow.store.models import Attempt, PracticeSession, Segment

router = APIRouter()


# Sync def on purpose: FastAPI runs it in the threadpool, so blocking ffmpeg/DB work never stalls the event loop.
# Phase 2: VAD-trim the 150 ms slack from uploaded attempt slices here (spec §6.1); deferred, not done in Phase 1.
@router.post("/segments/{segment_id}/attempts", response_model=AttemptOut, status_code=201)
def create_attempt(segment_id: int, request: Request, audio_file: UploadFile = File(..., alias="audio"),
                   session_id: int | None = Form(None), mode: str = Form("echo"), db: Session = Depends(get_session)):
    seg = db.get(Segment, segment_id)
    if seg is None:
        raise HTTPException(404, "segment not found")
    if mode not in MODES:
        raise HTTPException(400, "bad mode")
    sess = None
    if session_id is not None:
        sess = db.get(PracticeSession, session_id)
        if sess is None:
            raise HTTPException(404, "session not found")
    files, deps = request.app.state.files, request.app.state.deps
    tmp_dir = files.data_dir / "attempts" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    raw = tmp_dir / f"{uuid.uuid4().hex}.bin"
    raw.write_bytes(audio_file.file.read())
    att = Attempt(segment_id=segment_id, session_id=session_id, mode=mode, audio_path="", duration_s=0.0)
    db.add(att); db.commit(); db.refresh(att)
    dst = files.attempt_wav(att.id)
    try:
        audio.normalise(raw, dst)
        att.duration_s = audio.duration_s(dst)
    except (subprocess.CalledProcessError, KeyError, ValueError):
        dst.unlink(missing_ok=True)
        db.delete(att); db.commit()
        raise HTTPException(400, "audio could not be decoded")
    finally:
        raw.unlink(missing_ok=True)
    att.audio_path = str(dst)
    att.score_json = score_attempt(deps, seg, dst)
    if sess is not None:
        sess.attempts_count += 1; db.add(sess)
    db.add(att); db.commit(); db.refresh(att)
    return att


@router.get("/segments/{segment_id}/attempts", response_model=list[AttemptOut])
def list_attempts(segment_id: int, db: Session = Depends(get_session)):
    return db.exec(select(Attempt).where(Attempt.segment_id == segment_id)
                   .order_by(Attempt.created_at.desc(), Attempt.id.desc())).all()


@router.get("/attempts/{attempt_id}/audio")
def attempt_audio(attempt_id: int, db: Session = Depends(get_session)):
    att = db.get(Attempt, attempt_id)
    if att is None or not att.audio_path:
        raise HTTPException(404, "attempt not found")
    return FileResponse(att.audio_path, media_type="audio/wav")
