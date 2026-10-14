"""Drills (Phase 3b spec): focuses, sessions with their queue, summaries."""
from __future__ import annotations
from dataclasses import asdict
from fastapi import APIRouter, Depends, Request
from sqlmodel import Session
from shadow.drill.focus import auto_focus, rank_focuses
from shadow.store.db import get_session

router = APIRouter()


@router.get("/drill/focuses")
def focuses(request: Request, db: Session = Depends(get_session)):
    cfg = request.app.state.settings.drill
    fs = rank_focuses(db, cfg)
    auto = auto_focus(db, fs, cfg)
    return {"focuses": [asdict(f) for f in fs], "auto": {"kind": auto.kind, "key": auto.key} if auto else None}
