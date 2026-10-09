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
        "tone_model": _tone_model(loaded),
        "versions": {"fastapi": fastapi.__version__, "sqlmodel": sqlmodel.__version__, "pydantic": pydantic.__version__},
    }


def _tone_model(deps) -> dict:
    tm = getattr(deps, "tone_model", None) if deps else None
    meta = getattr(tm, "meta", {}) or {}
    return {"loaded": tm is not None, "version": getattr(tm, "version", None), "accuracy": meta.get("accuracy")}
