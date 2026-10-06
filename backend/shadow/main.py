from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from shadow.config import Settings, load_settings
from shadow.deps import Deps, build_deps
from shadow.jobs import JobManager
from shadow.store.db import make_engine, init_db
from shadow.api import anki, attempts, health, jobs, lessons, segments, sessions


def create_app(settings: Settings | None = None, deps: Deps | None = None) -> FastAPI:
    settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
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
    for r in (health.router, jobs.router, lessons.router, segments.router, anki.router, attempts.router, sessions.router):
        app.include_router(r)
    return app


app = create_app()
