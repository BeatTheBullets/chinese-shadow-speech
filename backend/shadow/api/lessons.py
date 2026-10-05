from __future__ import annotations
import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlmodel import Session
from shadow.ingest.pipeline import ingest_upload
from shadow.store.db import get_session
from shadow.store.models import Lesson

router = APIRouter()


def _save_upload(file: UploadFile, dest: Path) -> None:
    with dest.open("wb") as out:
        shutil.copyfileobj(file.file, out)


@router.post("/lessons", status_code=202)
async def create_lesson(request: Request, file: UploadFile = File(...), subtitles: UploadFile | None = File(None),
                        title: str = Form(""), speaker: str = Form(""), db: Session = Depends(get_session)):
    deps, engine, jobs = request.app.state.deps, request.app.state.engine, request.app.state.jobs
    filename = Path(file.filename or "upload").name          # never trust a client-supplied path
    lesson = Lesson(title=title or filename, speaker=speaker, source_type="upload", source_ref=filename)
    db.add(lesson); db.commit(); db.refresh(lesson)
    upload_dir = deps.files.lesson_dir(lesson.id) / "upload"
    upload_dir.mkdir(parents=True, exist_ok=True)
    media_path = upload_dir / f"{uuid.uuid4().hex[:8]}_{filename}"
    await run_in_threadpool(_save_upload, file, media_path)
    sub = None
    if subtitles is not None and subtitles.filename:
        sub = (Path(subtitles.filename).name, (await subtitles.read()).decode("utf-8-sig", errors="replace"))
    lesson_id = lesson.id
    job_id = jobs.submit(lambda progress: ingest_upload(deps, engine, lesson_id, media_path, sub, progress), lesson_id)
    return {"job_id": job_id, "lesson_id": lesson_id}
