from fastapi import APIRouter, Request
import fastapi, sqlmodel, pydantic

router = APIRouter()


@router.get("/health")
def health(request: Request):
    settings = request.app.state.settings
    loaded = getattr(request.app.state, "deps", None)
    return {
        "device": settings.resolved_device(),
        "aligner": settings.resolved_aligner(),
        "models_loaded": loaded.loaded_models() if loaded else [],
        "versions": {"fastapi": fastapi.__version__, "sqlmodel": sqlmodel.__version__, "pydantic": pydantic.__version__},
    }
