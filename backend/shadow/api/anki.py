from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlmodel import Session, select
from shadow.ingest.anki import AnkiNoteIn, group_by_video, handled_note_ids, ingest_anki_group, is_importable
from shadow.ingest.text import to_simplified
from shadow.store.db import get_session
from shadow.store.models import Lesson

router = APIRouter()


class AnkiImportIn(BaseModel):
    query_name: str
    notes: list[AnkiNoteIn]


@router.post("/lessons/anki", status_code=202)
def import_anki(body: AnkiImportIn, request: Request, db: Session = Depends(get_session)):
    """One lesson per source video; re-importing appends only notes not yet in that lesson."""
    deps, engine, jobs = request.app.state.deps, request.app.state.engine, request.app.state.jobs
    out = []
    for video, notes in group_by_video(body.notes).items():
        ref = f"{body.query_name}::{video}"
        lesson = db.exec(select(Lesson).where(Lesson.source_type == "anki", Lesson.source_ref == ref)).first()
        handled = handled_note_ids(engine, lesson.id) if lesson else set()
        new_notes = [n for n in notes if n.note_id not in handled and is_importable(n)]
        if not new_notes:
            continue
        if lesson is None:
            name = to_simplified(video or body.query_name)
            lesson = Lesson(title=name, speaker=to_simplified(video) or "Anki", source_type="anki", source_ref=ref)
            db.add(lesson); db.commit(); db.refresh(lesson)
        lid, title = lesson.id, lesson.title
        job_id = jobs.submit(lambda p, lid=lid, ns=new_notes: ingest_anki_group(deps, engine, lid, ns, p), lid)
        out.append({"job_id": job_id, "lesson_id": lid, "title": title})
    return {"jobs": out}
