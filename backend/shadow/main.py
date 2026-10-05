from fastapi import FastAPI
from shadow.config import Settings, load_settings
from shadow.api import health


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    app = FastAPI(title="shadow")
    app.state.settings = settings
    app.include_router(health.router)
    return app


app = create_app()
