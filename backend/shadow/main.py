from fastapi import FastAPI
from shadow.config import Settings, load_settings
from shadow.api import health
from shadow.store.db import make_engine, init_db
from shadow.store.files import FileLayout


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="shadow")
    app.state.settings = settings
    app.state.engine = make_engine(settings.data_dir)
    init_db(app.state.engine)
    app.state.files = FileLayout(settings.data_dir)
    app.include_router(health.router)
    return app


app = create_app()
