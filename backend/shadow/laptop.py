"""Laptop install support: the config the installer writes, where models live, and `python -m shadow.laptop prepare`,
which loads every model once so the app never downloads or quantises during a take or a lesson build."""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Callable

MANIFEST = "prepared.json"      # keep in sync with the Windows bootstrap, which reads it


def laptop_config_text(home: Path) -> str:
    data = json.dumps((Path(home) / "data").as_posix(), ensure_ascii=False)   # a TOML basic string
    return (f'data_dir = {data}\n\n'          # a top-level key: it must come before the tables
            '[models]\ndevice = "cpu"\nint8 = true\npunctuation = "sherpa"\n')


def ensure_laptop_config(home: Path) -> Path:
    """Write the laptop config at <home>/config.toml once; an existing file is never touched."""
    path = Path(home) / "config.toml"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(laptop_config_text(home), encoding="utf-8")
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


def _release(load) -> None:
    """Drop the model a loader just loaded (prepare only fills the caches), so the next load starts from an empty
    process: holding every model made prepare's peak the sum of all loads, building the int8 copies included."""
    owner = getattr(load, "__self__", None)
    for attr in ("_model", "_punct"):
        if owner is not None and getattr(owner, attr, None) is not None:
            setattr(owner, attr, None)
    import gc
    from shadow.memory import trim_heap
    gc.collect()
    trim_heap()


def manifest_path() -> Path:
    """<home>/models/prepared.json on the laptop, where SHADOW_MODELS_DIR is <home>/models/shadow (model_env).
    Without SHADOW_MODELS_DIR: inside the default models directory."""
    from shadow.ingest.punct import models_cache_dir
    root = models_cache_dir()
    return (root.parent if os.environ.get("SHADOW_MODELS_DIR") else root) / MANIFEST


def _hf_snapshot(name: str, revision: str) -> Path | None:
    """The cached Hugging Face snapshot directory of a model, or None (not cached, or no huggingface_hub)."""
    try:
        from huggingface_hub import snapshot_download
        return Path(snapshot_download(name, revision=revision, local_files_only=True))
    except Exception:  # noqa: BLE001 - only the manifest's checks of this model are lost
        return None


def prepared_files(deps) -> list[Path]:
    """The files the app needs at run time, as the loaders resolved them: the stored int8 copies, the punctuation
    model, the recogniser and VAD snapshots, and the config and weights of the Hugging Face models. Only files that
    exist: a listed file that prepare cannot bring back would rerun setup on every start."""
    from shadow.quant import stored_int8_paths
    files = list(stored_int8_paths())
    punct = getattr(getattr(deps.asr, "punctuator", None), "model_file", None)
    if punct is not None:
        files.append(Path(punct))
    model_id = getattr(deps.asr, "model_id", None)
    if isinstance(model_id, str):
        from shadow.ingest import asr
        for name in (model_id, "fsmn-vad"):
            snap = Path(asr._local_snapshot(name))
            if snap.is_dir():
                files += [snap / f for f in asr._MS_FILES]
    for owner in (deps.embedder, getattr(deps.sounds, "chars", None)):
        name, revision = getattr(owner, "name", None), getattr(owner, "revision", None)
        snap = _hf_snapshot(name, revision) if isinstance(name, str) else None
        if snap is not None and snap.is_dir():
            files += [snap / "config.json", *(f for f in snap.iterdir() if f.suffix in (".safetensors", ".bin"))]
    return [f for f in files if f.is_file()]


def write_manifest(path: Path, files: list[Path]) -> None:
    """The manifest the Windows bootstrap checks before each start: the quantisation format and the paths of the
    prepared files, relative to the manifest's folder and with /. Files outside that folder are left out. Atomic."""
    from shadow.quant import QUANT_FORMAT
    root = Path(os.path.abspath(path.parent))
    rel = set()
    for f in files:
        try:
            rel.add(Path(os.path.abspath(f)).relative_to(root).as_posix())
        except ValueError:
            continue
    root.mkdir(parents=True, exist_ok=True)
    tmp = root / f"{path.name}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps({"quant_format": QUANT_FORMAT, "files": sorted(rel)}, indent=1), encoding="utf-8")
    os.replace(tmp, root / path.name)


def run_prepare(deps, manifest: Path | None = None) -> int:
    """Load each model once, one at a time; after the last, write the manifest when given its path."""
    steps = prepare_steps(deps)
    total = len(steps)
    for i, (name, load) in enumerate(steps, 1):
        try:
            load()
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"error": f"{name}: {str(e) or type(e).__name__}"}), flush=True)
            return 1
        _release(load)
        print(json.dumps({"step": name, "done": i, "total": total}), flush=True)
    from shadow.quant import unsaved_int8
    if unsaved_int8():      # no manifest: the next start runs setup again instead of building the copy during a take
        print(json.dumps({"error": "Could not store the prepared speech models; check free disk space and press Retry"}),
              flush=True)
        return 1
    if manifest is not None:
        try:
            write_manifest(manifest, prepared_files(deps))
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"error": f"manifest: {str(e) or type(e).__name__}"}), flush=True)
            return 1
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
    return run_prepare(deps, manifest_path())


if __name__ == "__main__":
    sys.exit(main())
