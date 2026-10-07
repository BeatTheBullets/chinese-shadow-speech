from __future__ import annotations
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select
from shadow.api.lessons import _get_lesson
from shadow.api.sessions import MODES
from shadow.ingest import audio
from shadow.schemas import AttemptOut, FlowRunItem, FlowRunOut, FlowRunsOut, TakeOut, TakesOut
from shadow.scoring import score_attempt
from shadow.store.db import get_session
from shadow.store.models import Attempt, PracticeSession, Segment

router = APIRouter()

RUN_GAP_S = 60      # Flow attempts of one session further apart than this belong to different runs
MAX_RUNS = 10


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


def _utc(dt: datetime) -> datetime:
    """SQLite hands datetimes back naive; they are stored in UTC."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _has_audio(a: Attempt) -> bool:
    """Its audio endpoint serves a file: the upload was decoded (audio_path set) and the file is still there."""
    return bool(a.audio_path) and Path(a.audio_path).is_file()


def _lesson_attempts(db: Session, lesson_id: int, *where: Any) -> list[tuple[Attempt, int]]:
    """(attempt, its sentence's idx) for the lesson's decoded attempts matching `where`, newest first, from one query."""
    q = (select(Attempt, Segment.idx).join(Segment, Segment.id == Attempt.segment_id)
         .where(Segment.lesson_id == lesson_id, Attempt.audio_path != "", *where)
         .order_by(Attempt.created_at.desc(), Attempt.id.desc()))
    return list(db.exec(q).all())


def _latest_per_segment(rows: list[tuple[Attempt, int]]) -> list[tuple[Attempt, int]]:
    """The first playable attempt of each sentence in `rows` (newest first), in sentence order."""
    latest: dict[int, tuple[Attempt, int]] = {}
    for a, idx in rows:
        if a.segment_id not in latest and _has_audio(a):
            latest[a.segment_id] = (a, idx)
    return sorted(latest.values(), key=lambda r: r[1])


@router.get("/lessons/{lesson_id}/takes", response_model=TakesOut)
def lesson_takes(lesson_id: int, db: Session = Depends(get_session)):
    """The newest playable attempt of each sentence of the lesson, any mode, in sentence order: what R replays and
    the You track shows when the lesson is opened again."""
    _get_lesson(db, lesson_id)
    return TakesOut(takes=[TakeOut(segment_id=a.segment_id, attempt_id=a.id, mode=a.mode, created_at=_utc(a.created_at),
                                   duration_s=a.duration_s) for a, _ in _latest_per_segment(_lesson_attempts(db, lesson_id))])


@router.get("/lessons/{lesson_id}/flow-runs", response_model=FlowRunsOut)
def flow_runs(lesson_id: int, db: Session = Depends(get_session)):
    """The lesson's last MAX_RUNS Flow runs, newest first. A run is the flow attempts of one practice session (those
    without a session form one group), split wherever more than RUN_GAP_S pass between two of them; it lists the
    newest playable take of each of its sentences, in sentence order."""
    _get_lesson(db, lesson_id)
    groups: dict[int | None, list[tuple[Attempt, int]]] = {}
    for row in _lesson_attempts(db, lesson_id, Attempt.mode == "flow"):
        groups.setdefault(row[0].session_id, []).append(row)
    runs: list[list[tuple[Attempt, int]]] = []          # each newest first
    for rows in groups.values():
        run = [rows[0]]
        for row in rows[1:]:
            if (run[-1][0].created_at - row[0].created_at).total_seconds() > RUN_GAP_S:
                runs.append(run); run = []
            run.append(row)
        runs.append(run)
    runs.sort(key=lambda r: (r[-1][0].created_at, r[-1][0].id), reverse=True)
    out: list[FlowRunOut] = []
    for run in runs:                                    # a run with no playable take is left out, not counted
        if len(out) == MAX_RUNS:
            break
        items = [FlowRunItem(segment_id=a.segment_id, idx=idx, attempt_id=a.id) for a, idx in _latest_per_segment(run)]
        if items:
            out.append(FlowRunOut(started_at=_utc(run[-1][0].created_at), ended_at=_utc(run[0][0].created_at),
                                  session_id=run[0][0].session_id, items=items))
    return FlowRunsOut(runs=out)
