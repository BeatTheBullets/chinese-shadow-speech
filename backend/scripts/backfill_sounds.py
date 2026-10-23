"""Add wrong-sound results to every stored take scored before Phase 3a; tone results are never touched.

    cd backend && ~/.local/bin/uv run python scripts/backfill_sounds.py [--data-dir DIR] [--dry-run]
Takes are processed oldest first and committed every 20 (with a heap trim). --dry-run computes and prints the counts
but writes nothing: it opens the database read-only and skips the schema upgrade. Back up the database first."""
from __future__ import annotations
import argparse
from pathlib import Path
from sqlmodel import Session, create_engine
from shadow.config import load_settings
from shadow.deps import build_deps
from shadow.memory import release_freed_memory_eagerly, trim_heap
from shadow.scoring.sounds.backfill import backfill_all
from shadow.store.db import init_db, make_engine

EVERY = 20


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    settings = load_settings()
    if a.data_dir is not None:
        settings.data_dir = a.data_dir
    db_path = settings.data_dir / "shadow.db"
    if a.dry_run:                       # read-only, as in drop_failed_takes.py: not even init_db's schema upgrade
        if not db_path.is_file():           # make_engine would create the data dir and an empty database
            raise SystemExit(f"no database at {db_path}")
        engine = create_engine(f"sqlite:///file:{db_path}?mode=ro&uri=true")
    else:
        engine = make_engine(settings.data_dir); init_db(engine)
    release_freed_memory_eagerly()      # before any model loads
    deps = build_deps(settings)
    if deps.sounds is None:
        raise SystemExit(f"the sound detector is off: {deps.sounds_error or 'disabled in settings'}")
    with Session(engine) as db:
        c = backfill_all(deps, db, dry_run=a.dry_run, every=EVERY, after_commit=trim_heap)
    print(f"{'dry run: ' if a.dry_run else ''}{c['done']} done, {c['skipped']} skipped, {c['failed']} failed, {c['slips']} slips")


if __name__ == "__main__":
    main()
