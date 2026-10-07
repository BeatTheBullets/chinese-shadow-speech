from __future__ import annotations
import shutil
import uuid
from pathlib import Path
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from sqlmodel import Session, select
from shadow.ingest.pipeline import ingest_upload, ingest_youtube
from shadow.ingest.text import to_simplified
from shadow.ingest.youtube import parse_video_id, source_ref, watch_url
from shadow.schemas import LessonDetail, LessonOut, SegmentOut
from shadow.store.db import get_session
from shadow.store.files import FileLayout
from shadow.store.models import Attempt, Lesson, PracticeSession, Segment, SyllableScore

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


class YoutubeIn(BaseModel):
    url: str


@router.post("/lessons/youtube", status_code=202)
def add_youtube(body: YoutubeIn, request: Request, response: Response, db: Session = Depends(get_session)):
    """Addendum §2: one lesson per video (`source_ref` youtube::<id>). A video that already has a lesson returns it
    with no job, unless that lesson failed: then it is deleted and the video ingested again."""
    deps, engine, jobs = request.app.state.deps, request.app.state.engine, request.app.state.jobs
    if not request.app.state.settings.youtube.enabled:
        raise HTTPException(400, "YouTube lessons are off: set [youtube] enabled = true in config.toml")
    vid = parse_video_id(body.url)
    if vid is None:
        raise HTTPException(400, "not a YouTube video link (youtube.com/watch?v=…, youtu.be/…, youtube.com/shorts/…)")
    ref = source_ref(vid)
    existing = db.exec(select(Lesson).where(Lesson.source_type == "youtube", Lesson.source_ref == ref)).first()
    if existing is not None and existing.status != "error":
        response.status_code = 200
        return {"job_id": None, "lesson_id": existing.id}
    if existing is not None:
        _delete_lesson(db, request.app.state.files, existing)
    lesson = Lesson(title=vid, speaker="", source_type="youtube", source_ref=ref)
    db.add(lesson); db.commit(); db.refresh(lesson)
    lesson_id, url = lesson.id, watch_url(vid)
    job_id = jobs.submit(lambda progress: ingest_youtube(deps, engine, lesson_id, url, progress), lesson_id)
    return {"job_id": job_id, "lesson_id": lesson_id}


def _segment_out(db: Session, seg: Segment) -> SegmentOut:
    atts = db.exec(select(Attempt).where(Attempt.segment_id == seg.id).order_by(Attempt.created_at, Attempt.id)).all()
    scores = [a.score_json["overall"] for a in atts if a.score_json and "overall" in a.score_json]
    return SegmentOut(**seg.model_dump(), last_score=scores[-1] if scores else None,
                      best_score=max(scores) if scores else None, attempts=len(atts))


def _lesson_out(db: Session, lesson: Lesson) -> LessonOut:
    segs = db.exec(select(Segment).where(Segment.lesson_id == lesson.id)).all()
    outs = [_segment_out(db, s) for s in segs]
    last = [o.last_score for o in outs if o.last_score is not None]
    return LessonOut(**lesson.model_dump(exclude={"meta_json", "transcript_json"}), segment_count=len(segs),
                     practised_count=sum(1 for o in outs if o.attempts),
                     mean_last_score=sum(last) / len(last) if last else None)


def _get_lesson(db: Session, lesson_id: int) -> Lesson:
    lesson = db.get(Lesson, lesson_id)
    if lesson is None:
        raise HTTPException(404, "lesson not found")
    return lesson


def _delete_lesson(db: Session, files: FileLayout, lesson: Lesson) -> None:
    """Delete the lesson, its segments, their attempts and scores, its sessions and its files."""
    lesson_id = lesson.id
    segs = db.exec(select(Segment).where(Segment.lesson_id == lesson_id)).all()
    attempt_files: list[Path] = []
    if segs:
        seg_ids = [s.id for s in segs]
        for sc in db.exec(select(SyllableScore).where(SyllableScore.segment_id.in_(seg_ids))).all():
            db.delete(sc)
        for a in db.exec(select(Attempt).where(Attempt.segment_id.in_(seg_ids))).all():
            if a.audio_path:
                attempt_files.append(Path(a.audio_path))
            db.delete(a)
        db.flush()
    for ps in db.exec(select(PracticeSession).where(PracticeSession.lesson_id == lesson_id)).all():
        db.delete(ps)
    db.flush()
    for s in segs:
        db.delete(s)
    db.delete(lesson); db.commit()
    for f in attempt_files:
        f.unlink(missing_ok=True)
    shutil.rmtree(files.lesson_dir(lesson_id), ignore_errors=True)


@router.get("/lessons", response_model=list[LessonOut])
def list_lessons(db: Session = Depends(get_session)):
    lessons = db.exec(select(Lesson).order_by(Lesson.created_at.desc(), Lesson.id.desc())).all()
    return [_lesson_out(db, lesson) for lesson in lessons]


@router.get("/lessons/{lesson_id}", response_model=LessonDetail)
def get_lesson(lesson_id: int, db: Session = Depends(get_session)):
    base = _lesson_out(db, _get_lesson(db, lesson_id))
    segs = db.exec(select(Segment).where(Segment.lesson_id == lesson_id).order_by(Segment.idx)).all()
    return LessonDetail(**base.model_dump(), segments=[_segment_out(db, s) for s in segs])


class LessonPatch(BaseModel):
    title: str | None = None
    speaker: str | None = None


@router.patch("/lessons/{lesson_id}", response_model=LessonOut)
def patch_lesson(lesson_id: int, body: LessonPatch, db: Session = Depends(get_session)):
    lesson = _get_lesson(db, lesson_id)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(lesson, k, to_simplified(v))           # simplified everywhere (spec §3.2)
    db.add(lesson); db.commit(); db.refresh(lesson)
    return _lesson_out(db, lesson)


@router.delete("/lessons/{lesson_id}", status_code=204)
def delete_lesson(lesson_id: int, request: Request, db: Session = Depends(get_session)):
    """Deletes the lesson, its segments, their attempts and the lesson's files. An ingest job still running
    for it ends cleanly: its status updates become no-ops and it writes no segment rows."""
    _delete_lesson(db, request.app.state.files, _get_lesson(db, lesson_id))
