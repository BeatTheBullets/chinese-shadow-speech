import os
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from shadow.config import Settings, load_settings
from shadow.deps import Deps, build_deps
from shadow.jobs import JobManager
from sqlalchemy import Engine
from sqlmodel import Session, select
from shadow.store.db import make_engine, init_db
from shadow.store.models import Lesson
from shadow.api import anki, attempts, health, jobs, lessons, segments, sessions, stats


def create_app(settings: Settings | None = None, deps: Deps | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        recover_interrupted(app.state.engine)
        app.state.jobs.start()
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
    for r in (health.router, jobs.router, lessons.router, segments.router, anki.router, attempts.router, sessions.router, stats.router):
        app.include_router(r)
    _mount_spa(app)
    return app


INTERRUPTED = "interrupted — the server restarted during processing; delete and re-upload"


def recover_interrupted(engine: Engine) -> None:
    """Jobs live in memory, so after a restart no job runs for a queued/processing lesson: mark it as failed
    (once the app serves, not on import, so importing this module never touches a live server's lessons)."""
    with Session(engine) as db:
        for lesson in db.exec(select(Lesson).where(Lesson.status.in_(("queued", "processing")))).all():
            lesson.status, lesson.error = "error", INTERRUPTED
            db.add(lesson)
        db.commit()


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
