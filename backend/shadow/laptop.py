"""Laptop install support: the config the installer writes, where models live, and `python -m shadow.laptop prepare`,
which loads every model once so the app never downloads or quantises during a take or a lesson build."""
from __future__ import annotations
import json
import sys
from pathlib import Path
from typing import Callable


def laptop_config_text(home: Path) -> str:
    data = (Path(home) / "data").as_posix()
    return (f'data_dir = "{data}"\n\n'          # a top-level key: it must come before the tables
            '[models]\ndevice = "cpu"\nint8 = true\npunctuation = "sherpa"\n')


def ensure_laptop_config(home: Path) -> Path:
    """Write the laptop config at <home>/config.toml once; an existing file is never touched."""
    path = Path(home) / "config.toml"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(laptop_config_text(home))
    return path


def model_env(home: Path) -> dict[str, str]:
    models = Path(home) / "models"
    return {"HF_HOME": str(models / "hf"), "MODELSCOPE_CACHE": str(models / "modelscope"),
            "TORCH_HOME": str(models / "torch"), "SHADOW_MODELS_DIR": str(models / "shadow")}


def prepare_steps(deps) -> list[tuple[str, Callable[[], None]]]:
    """One named loader per model, in order. They call the loaders directly (not `warm`, which swallows failures),
    so a failed download surfaces. Loading the aligner and sounds model with int8 on builds their stored int8 copies."""
    steps: list[tuple[str, Callable[[], None]]] = [("recogniser", deps.asr._load)]
    punct_load = getattr(getattr(deps.asr, "punctuator", None), "_load", None)
    if punct_load is not None:
        steps.append(("punctuation model", punct_load))
    steps.append(("aligner", getattr(deps.aligner, "inner", deps.aligner)._load))
    steps.append(("tone model", deps.embedder._load))
    chars = getattr(deps.sounds, "chars", None)
    if chars is not None:
        steps.append(("sound model", chars._load))
    return steps


def run_prepare(deps) -> int:
    steps = prepare_steps(deps)
    total = len(steps)
    for i, (name, load) in enumerate(steps, 1):
        try:
            load()
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"error": f"{name}: {str(e) or type(e).__name__}"}), flush=True)
            return 1
        print(json.dumps({"step": name, "done": i, "total": total}), flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv != ["prepare"]:
        print("usage: python -m shadow.laptop prepare", file=sys.stderr)
        return 2
    try:
        from shadow.config import load_settings
        from shadow.deps import build_deps
        deps = build_deps(load_settings())
    except Exception as e:  # noqa: BLE001
        print(json.dumps({"error": str(e) or type(e).__name__}), flush=True)
        return 1
    return run_prepare(deps)


if __name__ == "__main__":
    sys.exit(main())
