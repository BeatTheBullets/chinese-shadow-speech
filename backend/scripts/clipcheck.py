"""Check that each sentence's clip says its text: the recogniser hears every clip and the words check compares.

    cd backend && ~/.local/bin/uv run python scripts/clipcheck.py --lesson N     (or --all)
Read only. For each sentence the app's hearer (the Paraformer model ingest uses) transcribes its clip and
`text_similarity` (the words check of attempt scoring, toneless pinyin) compares that with the sentence's syllables.
Prints the sentences below 0.8 and per lesson n, how many match (>= 0.8) and the mean. A lesson whose text drifted
from its audio (the FunASR sentence_info bug) scores far below its neighbours; Rebuild text in the library fixes it."""
from __future__ import annotations
import argparse
from pathlib import Path
from sqlmodel import Session, select
from shadow.ingest.asr import Hearer
from shadow.scoring.gate import text_similarity
from shadow.scoring.reference import segment_syllables
from shadow.store.models import Lesson, Segment

MATCH = 0.8


def check_lesson(db: Session, hearer: Hearer, lesson_id: int) -> list[tuple[Segment, str, float]]:
    """(segment, heard text, similarity) per segment with a clip, in idx order."""
    out = []
    segs = db.exec(select(Segment).where(Segment.lesson_id == lesson_id).order_by(Segment.idx)).all()
    for seg in segs:
        if not seg.clip_wav_path or not Path(seg.clip_wav_path).exists():
            continue
        heard = hearer.hear(Path(seg.clip_wav_path)) or ""
        out.append((seg, heard, text_similarity(segment_syllables(seg), heard)))
    return out


def report(title: str, rows: list[tuple[Segment, str, float]]) -> str:
    lines = [f"{seg.idx:3d} {seg.start_s:7.2f}-{seg.end_s:7.2f} sim={sim:.2f} text={seg.text!r} clip={heard!r}"
             for seg, heard, sim in rows if sim < MATCH]
    sims = [sim for _, _, sim in rows]
    mean = f"{sum(sims) / len(sims):.2f}" if sims else "-"
    lines.append(f"{title}: n={len(sims)} matched={sum(s >= MATCH for s in sims)} (sim >= {MATCH}) mean={mean}")
    return "\n".join(lines)


def main() -> None:
    from shadow.config import load_settings
    from shadow.ingest.asr import AsrHearer, ParaformerASR
    from shadow.store.db import make_engine
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument("--lesson", type=int)
    which.add_argument("--all", action="store_true")
    a = ap.parse_args()
    settings = load_settings()
    engine = make_engine(settings.data_dir)
    hearer = AsrHearer(ParaformerASR(settings.models.asr, settings.resolved_device()))
    with Session(engine) as db:
        if a.all:
            lessons = db.exec(select(Lesson).where(Lesson.status == "ready").order_by(Lesson.id)).all()
        else:
            lessons = [lesson] if (lesson := db.get(Lesson, a.lesson)) is not None else []
            if not lessons:
                raise SystemExit(f"no lesson {a.lesson}")
        for lesson in lessons:
            print(report(f"lesson {lesson.id} {lesson.title!r}", check_lesson(db, hearer, lesson.id)), flush=True)


if __name__ == "__main__":
    main()
