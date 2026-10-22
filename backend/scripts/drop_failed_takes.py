"""Delete the stored takes the recording gates rejected (score_json.warnings[0] in DROP_WARNINGS): their audio, their
SyllableScore rows and the attempt. Since Task 14 such takes are dropped on upload; this removes the older ones.

    cd backend && ~/.local/bin/uv run python scripts/drop_failed_takes.py [--data-dir DIR] [--dry-run]
Takes failing for server-side reasons (score_failed, no_reference, no_tone_model) are kept. --dry-run prints the
counts but writes nothing. Back up the database first."""
from __future__ import annotations
import argparse
from collections import Counter
from pathlib import Path
from sqlmodel import Session, create_engine, select
from shadow.api.attempts import dropped, drop_attempt
from shadow.config import load_settings
from shadow.store.db import init_db, make_engine
from shadow.store.files import FileLayout
from shadow.store.models import Attempt


def drop_failed(db: Session, files: FileLayout, dry_run: bool) -> dict[str, int]:
    """The number of takes dropped (or, on a dry run, that would be) per first warning."""
    n: Counter[str] = Counter()
    for att in db.exec(select(Attempt).order_by(Attempt.id)).all():
        if dropped(att):
            n[att.score_json["warnings"][0]] += 1        # type: ignore[index]  # dropped() checked it
            if not dry_run:
                drop_attempt(db, files, att)
    return dict(n)


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    settings = load_settings()
    if a.data_dir is not None:
        settings.data_dir = a.data_dir
    db_path = settings.data_dir / "shadow.db"
    if not db_path.is_file():
        raise SystemExit(f"no database at {db_path}")
    if a.dry_run:                       # read-only: not even init_db's schema upgrade may write
        engine = create_engine(f"sqlite:///file:{db_path}?mode=ro&uri=true")
    else:
        engine = make_engine(settings.data_dir); init_db(engine)
    with Session(engine) as db:
        n = drop_failed(db, FileLayout(settings.data_dir), dry_run=a.dry_run)
    detail = ", ".join(f"{k} {v}" for k, v in sorted(n.items(), key=lambda kv: -kv[1])) or "none"
    print(f"{'dry run: would drop' if a.dry_run else 'dropped'} {sum(n.values())} takes ({detail})")


if __name__ == "__main__":
    main()
