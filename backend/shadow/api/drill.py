"""Drills (Phase 3b spec): focuses, sessions with their queue, summaries."""
from __future__ import annotations
from dataclasses import asdict
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlmodel import Session
from shadow.api.lessons import _segment_out
from shadow.drill.focus import auto_focus, focus_label, rank_focuses
from shadow.drill.queue import build_queue, queue_from_ids
from shadow.drill.summary import recent_sessions, session_summary
from shadow.ingest.text import is_hanzi
from shadow.scoring.reference import segment_syllables
from shadow.scoring.sounds.contrasts import DIRECTIONS
from shadow.store.db import get_session
from shadow.store.models import DrillSession, Lesson

router = APIRouter()


@router.get("/drill/focuses")
def focuses(request: Request, db: Session = Depends(get_session)):
    cfg = request.app.state.settings.drill
    fs = rank_focuses(db, cfg)
    auto = auto_focus(db, fs, cfg)
    return {"focuses": [asdict(f) for f in fs], "auto": {"kind": auto.kind, "key": auto.key} if auto else None}


class SessionIn(BaseModel):
    kind: str
    key: str
    segment_ids: list[int] | None = None


class SessionPatch(BaseModel):
    ended: bool = False


def _valid(kind: str, key: str) -> bool:
    if kind == "tone":
        return key in {"1", "2", "3", "4"}
    if kind == "pair":
        parts = key.split("-")
        return len(parts) == 2 and all(p in {"1", "2", "3", "4"} for p in parts)
    if kind == "sound":
        return key in DIRECTIONS
    return kind == "char" and len(key) == 1 and is_hanzi(key)


@router.post("/drill/sessions", status_code=201)
def create_drill(body: SessionIn, request: Request, db: Session = Depends(get_session)):
    if not _valid(body.kind, body.key):
        raise HTTPException(400, "bad focus")
    deps = request.app.state.deps
    if body.kind == "sound" and deps.sounds is None:
        # every take would come back unchecked, so no item could go green: refuse and say why (the Drill page shows it)
        raise HTTPException(409, f"sound checking is off: {deps.sounds_error or 'not available'}")
    cfg = request.app.state.settings.drill
    items = (queue_from_ids(db, body.segment_ids, body.kind, body.key) if body.segment_ids is not None
             else build_queue(db, cfg, body.kind, body.key))
    if not items:
        raise HTTPException(404, "no sentences contain this focus")
    pinyin = next((s["pinyin_toneless"] for seg, t in items for i, s in enumerate(segment_syllables(seg)) if i in t), None)
    ds = DrillSession(kind=body.kind, key=body.key, label=focus_label(body.kind, body.key, pinyin if body.kind == "char" else None),
                      items_json=[{"segment_id": s.id, "targets": t} for s, t in items])
    db.add(ds); db.commit(); db.refresh(ds)
    # max_tries rides along so the runner's retry rule follows [drill] max_tries.
    return {"id": ds.id, "kind": ds.kind, "key": ds.key, "label": ds.label, "short": len(items) < cfg.queue_size,
            "max_tries": cfg.max_tries,
            "items": [{"segment": _segment_out(db, s), "lesson_id": s.lesson_id,
                       "lesson_title": db.get(Lesson, s.lesson_id).title, "targets": t} for s, t in items]}


@router.patch("/drill/sessions/{session_id}")
def end_drill(session_id: int, body: SessionPatch, db: Session = Depends(get_session)):
    ds = db.get(DrillSession, session_id)
    if ds is None:
        raise HTTPException(404, "drill session not found")
    if body.ended and ds.ended_at is None:
        ds.ended_at = datetime.now(timezone.utc); db.add(ds); db.commit(); db.refresh(ds)
    return {"id": ds.id, "kind": ds.kind, "key": ds.key, "label": ds.label, "started_at": ds.started_at, "ended_at": ds.ended_at}


@router.get("/drill/sessions/{session_id}/summary")
def drill_summary(session_id: int, db: Session = Depends(get_session)):
    ds = db.get(DrillSession, session_id)
    if ds is None:
        raise HTTPException(404, "drill session not found")
    return session_summary(db, ds)


@router.get("/drill/sessions")
def drill_sessions(limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_session)):
    return {"sessions": recent_sessions(db, limit)}
