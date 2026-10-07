"""Compare Qwen3 (raw and repaired), MMS_FA and the ASR char times on one ingested lesson (addendum spec §1.1).

Run manually, with the models extra installed and a GPU (Qwen3 needs one):
    cd backend && ~/.local/bin/uv run python scripts/compare_aligners.py --lesson 1
Prints, per source, the first-character onset error against an energy onset and the share of zero-length spans,
then a verdict line. MMS_FA downloads ~1.2 GB on first use."""
from __future__ import annotations
import argparse
from sqlmodel import Session, select
from shadow.config import load_settings
from shadow.ingest import audio
from shadow.ingest.align import Span, align_in_window, make_aligner
from shadow.ingest.aligncheck import energy_onset, onset_error, verdict, zero_length_share
from shadow.ingest.repair import clamp_spans, coarse_times, repair_spans
from shadow.ingest.text import is_punct
from shadow.ingest.transcript import Transcript
from shadow.store.db import make_engine
from shadow.store.files import FileLayout
from shadow.store.models import Lesson, Segment

MARGIN_S = 1.0          # the same alignment window as the pipeline (spec §3.4)


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--lesson", type=int, required=True)
    args = ap.parse_args()
    settings = load_settings()
    engine, files = make_engine(settings.data_dir), FileLayout(settings.data_dir)
    with Session(engine) as db:
        lesson = db.get(Lesson, args.lesson)
        if lesson is None or not lesson.transcript_json:
            raise SystemExit(f"lesson {args.lesson} not found or has no transcript (Anki lessons cannot be compared)")
        segs = db.exec(select(Segment).where(Segment.lesson_id == lesson.id).order_by(Segment.idx)).all()
    tr = Transcript.from_json(lesson.transcript_json)
    wav, sr = audio.read_wav(files.source_wav(lesson.id))
    total = len(wav) / sr
    device = settings.resolved_device()
    aligners = {"qwen3_fa": make_aligner("qwen3_fa", device), "mms_fa": make_aligner("mms_fa", device)}
    onsets: dict[str, list[float | None]] = {k: [] for k in ("asr", "qwen3_raw", "qwen3_repaired", "mms_fa")}
    spans: dict[str, list[list[Span]]] = {k: [] for k in ("qwen3_raw", "qwen3_repaired", "mms_fa")}
    truth: list[float | None] = []
    prev_end = 0.0
    for s in segs:
        if s.char_from is None or s.char_to is None:
            continue
        chars = tr.chars[s.char_from:s.char_to + 1]
        speech = [c for c in chars if not is_punct(c.c)]
        if not speech:
            continue
        c0, c1 = speech[0].start, speech[-1].end
        truth.append(energy_onset(wav, sr, max(prev_end, c0 - 0.5), c1))
        prev_end = c1
        onsets["asr"].append(c0)
        win = (max(0.0, chars[0].start - MARGIN_S), min(total, chars[-1].end + MARGIN_S))   # as build_segments
        coarse = coarse_times(s.text, chars)
        for name, aligner in aligners.items():
            try:
                got = align_in_window(aligner, wav, sr, s.text, *win)
            except Exception as e:  # noqa: BLE001  report and carry on
                print(f"sentence {s.idx}: {name} failed: {e}")
                got = []
            for key in (("qwen3_raw", "qwen3_repaired") if name == "qwen3_fa" else ("mms_fa",)):
                sp = clamp_spans(repair_spans(got, coarse), *win) if key == "qwen3_repaired" else got
                spans[key].append(sp)
                onsets[key].append(sp[0].start if sp else None)
    print(f"lesson {lesson.id} · {len(truth)} sentences · device {device}")
    print(f"{'source':16} {'n':>4} {'mean ms':>8} {'median':>8} {'<=100ms':>8} {'zero-len':>8}")
    results = {}
    for key, pred in onsets.items():
        e = onset_error(pred, truth)
        z = zero_length_share(spans[key]) if key in spans else 0.0
        results[key] = (e, z)
        print(f"{key:16} {e.n:>4} {e.mean_ms:>8} {e.median_ms:>8} {e.within_100ms:>8} {z:>8.3f}")
    print("verdict:", verdict(*results["qwen3_repaired"], *results["mms_fa"]))


if __name__ == "__main__":
    main()
