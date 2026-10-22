"""Add wrong-sound results to every stored take scored before Phase 3a; tone results are never touched.

    cd backend && ~/.local/bin/uv run python scripts/backfill_sounds.py [--data-dir DIR] [--dry-run]
Takes are processed oldest first and committed every 20 (with a heap trim). --dry-run computes and prints the counts
but writes nothing. Back up the database first."""
from __future__ import annotations
import argparse
from pathlib import Path
from sqlmodel import Session, select
from shadow.config import load_settings
from shadow.deps import build_deps
from shadow.memory import trim_heap
from shadow.scoring.sounds.backfill import backfill_attempt
from shadow.store.db import init_db, make_engine
from shadow.store.models import Attempt

EVERY = 20


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    settings = load_settings()
    if a.data_dir is not None:
        settings.data_dir = a.data_dir
    engine = make_engine(settings.data_dir); init_db(engine)
    deps = build_deps(settings)
    if deps.sounds is None:
        raise SystemExit(f"the sound detector is off: {deps.sounds_error or 'disabled in settings'}")
    done = skipped = slips = 0
    with Session(engine) as db:
        for n, att in enumerate(db.exec(select(Attempt).order_by(Attempt.created_at, Attempt.id)).all(), 1):
            if backfill_attempt(deps, db, att):
                done += 1; slips += (att.score_json or {}).get("sounds_off") or 0
            else:
                skipped += 1
            if n % EVERY == 0:
                db.rollback() if a.dry_run else db.commit()
                trim_heap()
        db.rollback() if a.dry_run else db.commit()
    print(f"{'dry run: ' if a.dry_run else ''}{done} done, {skipped} skipped, {slips} slips")


if __name__ == "__main__":
    main()
