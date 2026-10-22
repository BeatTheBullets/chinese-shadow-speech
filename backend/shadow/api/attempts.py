from __future__ import annotations
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from sqlmodel import Session, select
from shadow.api.lessons import _get_lesson, ensure_idle
from shadow.api.sessions import MODES
from shadow.ingest import audio
from shadow.memory import trim_heap
from shadow.schemas import AttemptOut, FlowRunItem, FlowRunOut, FlowRunsOut, TakeOut, TakesOut
from shadow.scoring import score_attempt
from shadow.store.db import get_session
from shadow.store.files import FileLayout
from shadow.store.models import Attempt, DrillSession, PracticeSession, Segment, SyllableScore

router = APIRouter()

# A take rejected because of the recording itself (its first warning) is not kept: no audio, no row, no try. Takes
# failing for server-side reasons (score_failed, no_reference, no_tone_model) stay, they can be rescored later.
DROP_WARNINGS = frozenset({"too_short", "too_quiet", "no_voice", "clipped", "wrong_or_unclear", "different_words", "align_failed"})

RUN_GAP_S = 60      # Flow attempts of one session further apart than this belong to different runs
MAX_RUNS = 10


# Sync def on purpose: FastAPI runs it in the threadpool, so blocking ffmpeg/DB work never stalls the event loop.
# Phase 2: VAD-trim the 150 ms slack from uploaded attempt slices here (spec §6.1); deferred, not done in Phase 1.
@router.post("/segments/{segment_id}/attempts", response_model=AttemptOut, status_code=201)
def create_attempt(segment_id: int, request: Request, response: Response, audio_file: UploadFile = File(..., alias="audio"),
                   session_id: int | None = Form(None), drill_session_id: int | None = Form(None), mode: str = Form("echo"), db: Session = Depends(get_session)):
    seg = db.get(Segment, segment_id)
    if seg is None:
        raise HTTPException(404, "segment not found")
    ensure_idle(db, seg.lesson_id)
    if mode not in MODES:
        raise HTTPException(400, "bad mode")
    sess = None
    if session_id is not None:
        sess = db.get(PracticeSession, session_id)
        if sess is None:
            raise HTTPException(404, "session not found")
    if drill_session_id is not None and db.get(DrillSession, drill_session_id) is None:
        raise HTTPException(404, "drill session not found")
    files, deps = request.app.state.files, request.app.state.deps
    tmp_dir = files.data_dir / "attempts" / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    raw = tmp_dir / f"{uuid.uuid4().hex}.bin"
    raw.write_bytes(audio_file.file.read())
    att = Attempt(segment_id=segment_id, session_id=session_id, drill_session_id=drill_session_id, mode=mode, audio_path="", duration_s=0.0)
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
    db.add(att); db.commit()            # the take is saved before scoring, which must not hold SQLite's write lock
    score_attempt(deps, db, seg, att)
    trim_heap()
    if dropped(att):                    # nothing stored, so 200 rather than 201; the score still says why
        out = AttemptOut(id=None, segment_id=att.segment_id, session_id=att.session_id, created_at=att.created_at,
                         mode=att.mode, duration_s=att.duration_s, score_json=att.score_json, dropped=True)
        drop_attempt(db, files, att)
        response.status_code = 200
        return out
    if sess is not None:
        sess.attempts_count += 1; db.add(sess)
    db.add(att); db.commit(); db.refresh(att)
    return att


def dropped(att: Attempt) -> bool:
    """Its score's first warning says the recording itself failed (DROP_WARNINGS)."""
    warnings = (att.score_json or {}).get("warnings") or []
    return bool(warnings) and warnings[0] in DROP_WARNINGS


def drop_attempt(db: Session, files: FileLayout, att: Attempt) -> None:
    """Deletes the attempt with its SyllableScore rows (a gated take has none), commits, then removes its audio: a
    failed commit leaves the row with its file, never a row whose audio is gone. The audio is looked for under the
    data dir too, in case the stored path predates a move of the data dir."""
    paths = {files.attempt_wav(att.id or 0), *([Path(att.audio_path)] if att.audio_path else [])}
    for sc in db.exec(select(SyllableScore).where(SyllableScore.attempt_id == att.id)).all():
        db.delete(sc)
    db.delete(att); db.commit()
    for p in paths:
        p.unlink(missing_ok=True)


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
                                   duration_s=a.duration_s, score_json=a.score_json) for a, _ in _latest_per_segment(_lesson_attempts(db, lesson_id))])


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
        items = [FlowRunItem(segment_id=a.segment_id, idx=idx, attempt_id=a.id, duration_s=a.duration_s) for a, idx in _latest_per_segment(run)]
        if items:
            out.append(FlowRunOut(started_at=_utc(run[-1][0].created_at), ended_at=_utc(run[0][0].created_at),
                                  session_id=run[0][0].session_id, items=items))
    return FlowRunsOut(runs=out)
