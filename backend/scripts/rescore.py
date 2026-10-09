"""Re-score every stored take (Phase 2 spec §5.4) and write a sanity report.

    cd backend && ~/.local/bin/uv run python scripts/rescore.py [--probe]
Clears all SyllableScore rows and the voice profile, then scores takes oldest first (the profile rebuilds as it
goes). --probe also aligns each take to the *next* sentence's text and prints level and alignment-confidence
percentiles for genuine and wrong-text takes, to set the gate thresholds (plan Task 15)."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date
from pathlib import Path
import numpy as np
from sqlmodel import Session, delete, select
from shadow.config import load_settings
from shadow.deps import build_deps
from shadow.ingest import audio
from shadow.scoring import score_attempt
from shadow.scoring.pitch import trim_silence
from shadow.scoring.profile import reset_profile
from shadow.scoring.report import ReportItem, render_report
from shadow.store.db import init_db, make_engine
from shadow.store.models import Attempt, Lesson, Segment, SyllableScore


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    a = ap.parse_args()
    settings = load_settings()
    engine = make_engine(settings.data_dir); init_db(engine)
    deps = build_deps(settings)
    if deps.tone_model is None:
        raise SystemExit("no tone model: train it first (make tone-model)")
    items, warn, dbfs, conf, wrong_conf = [], Counter(), [], [], []
    with Session(engine) as db:
        db.exec(delete(SyllableScore)); reset_profile(db); db.commit()
        atts = db.exec(select(Attempt).where(Attempt.audio_path != "").order_by(Attempt.created_at, Attempt.id)).all()
        for att in atts:
            if not Path(att.audio_path).exists():
                continue
            seg = db.get(Segment, att.segment_id)
            score_attempt(deps, db, seg, att)
            db.add(att); db.commit()
            sj = att.score_json or {}
            warn.update(sj.get("warnings") or ["scored"])
            q = sj.get("quality") or {}
            if q.get("dbfs") is not None: dbfs.append(q["dbfs"])
            if q.get("align_conf") is not None: conf.append(q["align_conf"])
            if a.probe:
                other = db.exec(select(Segment).where(Segment.lesson_id == seg.lesson_id, Segment.idx == seg.idx + 1)).first()
                if other is not None:
                    wav, sr = audio.read_wav(Path(att.audio_path))
                    spans = deps.aligner.align(trim_silence(wav, sr)[0], sr, other.text)
                    if spans: wrong_conf.append(float(np.mean([s.conf for s in spans])))
            items.append(ReportItem(att.id, seg.id, db.get(Lesson, seg.lesson_id).title, seg.text, str(att.created_at)[:16], sj))
    out = settings.data_dir / "reports" / f"rescore-{date.today().isoformat()}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(items, a.api), encoding="utf-8")
    scored = [i.score["overall"] for i in items if i.score and i.score.get("overall") is not None]
    print(f"{len(items)} takes; outcomes {dict(warn)}; mean overall {np.mean(scored):.2f}" if scored else f"{len(items)} takes; {dict(warn)}")
    pc = lambda xs: np.round(np.percentile(xs, [0, 5, 50, 95, 100]), 3).tolist() if xs else []
    print(f"dbfs p0/5/50/95/100: {pc(dbfs)}\nalign_conf (genuine): {pc(conf)}")
    if a.probe:
        print(f"align_conf (next sentence's text): {pc(wrong_conf)}")
    print(f"report: {out}")


if __name__ == "__main__":
    main()
