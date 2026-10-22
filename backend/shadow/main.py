import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from shadow.config import Settings, load_settings
from shadow.deps import Deps, build_deps
from shadow.jobs import JobManager
from shadow.ingest.asr import ParaformerASR
from shadow.ingest.rebuild import recover_rebuild
from shadow.scoring.embed import Wav2Vec2Embedder
from shadow.scoring.sounds.charctc import CharCtc
from sqlalchemy import Engine
from sqlmodel import Session, select
from shadow.store.db import make_engine, init_db
from shadow.store.models import Lesson, Segment
from shadow.api import anki, attempts, drill, health, jobs, lessons, review, segments, sessions, stats, voice

log = logging.getLogger(__name__)


def watch_sounds_warm_up(deps: Deps, warm: threading.Thread) -> None:
    """warm_up logs and swallows its failure: surface it on /health and switch sounds off for this process, so a
    failing ~1.2 GB load is not retried on every take (memory is tight)."""
    warm.join()
    chars = deps.sounds.chars if deps.sounds is not None else None
    if chars is not None and chars._model is None:
        deps.sounds_error = chars.load_error or "the sound model failed to load"
        deps.sounds = None


def create_app(settings: Settings | None = None, deps: Deps | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        recover_interrupted(app.state.engine, app.state.deps)
        app.state.jobs.start()
        if isinstance(app.state.deps.embedder, Wav2Vec2Embedder):     # real deps only: tests never download
            app.state.deps.embedder.warm_up()
        if isinstance(app.state.deps.asr, ParaformerASR):          # the words check of every take uses it
            app.state.deps.asr.warm_up()
        sounds = app.state.deps.sounds
        if isinstance(getattr(sounds, "chars", None), CharCtc):          # real deps only
            warm = sounds.chars.warm_up()
            threading.Thread(target=watch_sounds_warm_up, args=(app.state.deps, warm), name="charctc-warm-up-watch",
                             daemon=True).start()
        yield
        await app.state.jobs.stop()

    app = FastAPI(title="shadow", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = make_engine(settings.data_dir)
    init_db(app.state.engine)
    app.state.deps = deps or build_deps(settings)
    app.state.files = app.state.deps.files
    app.state.jobs = JobManager()
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])
    for r in (health.router, jobs.router, lessons.router, review.router, segments.router, anki.router, attempts.router, sessions.router, stats.router, voice.router, drill.router):
        app.include_router(r)
    _mount_spa(app)
    return app


INTERRUPTED = "interrupted — the server restarted during processing; delete and re-upload"


def recover_interrupted(engine: Engine, deps: Deps | None = None) -> None:
    """Jobs live in memory, so after a restart no job runs for a queued/processing lesson (once the app serves, not
    on import, so importing this module never touches a live server's lessons). A lesson without segments failed its
    ingest: `error`. One with segments was being rebuilt or updated by an Anki import: ingest writes a lesson's
    segments in one commit, a rebuild interrupted midway is put back together (`recover_rebuild`), so its segments
    are consistent and it goes back to `ready` with its takes rather than to an error whose advice is to delete it."""
    with Session(engine) as db:
        ids = db.exec(select(Lesson.id).where(Lesson.status.in_(("queued", "processing")))).all()
    for lesson_id in ids:
        if deps is not None:
            try:
                recover_rebuild(deps, engine, lesson_id)
            except Exception:  # noqa: BLE001
                log.exception("lesson %d: recovering an interrupted rebuild failed", lesson_id)
        with Session(engine) as db:
            lesson = db.get(Lesson, lesson_id)
            has_segments = db.exec(select(Segment.id).where(Segment.lesson_id == lesson_id)).first() is not None
            lesson.status, lesson.error = ("ready", None) if has_segments else ("error", INTERRUPTED)
            db.add(lesson); db.commit()


def _mount_spa(app: FastAPI) -> None:
    """Serve the built frontend, if present. Registered after the API routers so they win."""
    dist = Path(os.environ.get("SHADOW_FRONTEND_DIST", Path(__file__).resolve().parents[2] / "frontend" / "dist")).resolve()
    index = dist / "index.html"
    if not index.exists():
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_relative_to(dist) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()
