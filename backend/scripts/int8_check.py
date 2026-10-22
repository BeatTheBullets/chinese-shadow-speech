"""int8 validation: does the 8-bit recogniser / aligner give the same answers as fp32? (laptop-fit plan, Task 6)

    uv run python scripts/int8_check.py align --lesson 1 [--half fp32|int8|report]
    uv run python scripts/int8_check.py words [--half ...] [--limit N]
    uv run python scripts/int8_check.py cer   [--half ...]

Each check has two model halves, run in separate processes if memory is tight, and a report that needs no model:
  fp32   today's models (on the GPU when there is one), result cached as JSON
  int8   the 8-bit models on the CPU (run with CUDA_VISIBLE_DEVICES=""), result cached as JSON
  report compares the two cached files, prints the numbers and PASS or FAIL (default `all` runs the three in turn).
--data-dir (default: the settings' data dir) is only read; the database is opened read-only. Every cached result goes
under this checkout's data/cache/int8-check/. CER also reads the audio cached by split_gate.py under
data/cache/split-gate/ (run split_gate.py first so the gate's videos are there).

Pass marks: mean onset error within 10 ms of fp32; words-check verdict agreement >= 95 %; transcript CER <= 2 %."""
from __future__ import annotations
import argparse
import gc
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

CACHE = ROOT / "data" / "cache" / "int8-check"
GATE_CACHE = ROOT / "data" / "cache" / "split-gate"
ONSET_MARGIN_MS = 10.0
AGREEMENT_MIN = 0.95
CER_MAX = 0.02
MARGIN_S = 1.0          # the pipeline's alignment window


# ---- pure helpers (unit-tested without models) ----

def verdict_of(sim: float, min_sim: float, ok_at: float) -> str:
    """The words check's three outcomes for a text similarity."""
    if sim < min_sim:
        return "different"
    return "some" if sim < ok_at else "clean"


def agreement(a: list[str], b: list[str]) -> float:
    if len(a) != len(b):
        raise ValueError("verdict lists differ in length")
    return sum(x == y for x, y in zip(a, b)) / len(a) if a else 1.0


def squash(text: str) -> str:
    """Characters only: punctuation and whitespace removed."""
    from shadow.ingest.text import is_punct
    return "".join(c for c in text if not is_punct(c) and not c.isspace())


def cer(refs: list[str], hyps: list[str]) -> float:
    """Pooled character error rate of hyps against refs (punctuation removed): total edits / total reference length."""
    from rapidfuzz.distance import Levenshtein
    pairs = [(squash(r), squash(h)) for r, h in zip(refs, hyps)]
    total = sum(len(r) for r, _ in pairs)
    return sum(Levenshtein.distance(r, h) for r, h in pairs) / total if total else 0.0


def device_for(half: str) -> str:
    if half == "int8":
        return "cpu"
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def cache_file(name: str) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    return CACHE / name


def load_json(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def release() -> None:
    gc.collect()
    try:
        import torch
        torch.cuda.empty_cache()
    except Exception:  # noqa: BLE001
        pass


def readonly_session(data_dir: Path):
    from sqlalchemy import create_engine
    from sqlmodel import Session
    db = data_dir / "shadow.db"
    if not db.exists():
        raise SystemExit(f"no database at {db}")
    return Session(create_engine(f"sqlite:///file:{db}?mode=ro&uri=true"))     # never writes the user's data


def halves(half: str) -> list[str]:
    return ["fp32", "int8", "report"] if half == "all" else [half]


# ---- align ----

def align_half(half: str, lesson_id: int, data_dir: Path) -> None:
    out = cache_file(f"align-{half}-lesson{lesson_id}.json")
    if out.exists():
        print(f"{out.name}: cached")
        return
    from sqlmodel import select
    from shadow.ingest import audio
    from shadow.ingest.align import MmsAligner, align_in_window
    from shadow.ingest.aligncheck import energy_onset
    from shadow.ingest.repair import clamp_spans, coarse_times, repair_spans
    from shadow.ingest.text import is_punct
    from shadow.ingest.transcript import Transcript
    from shadow.store.files import FileLayout
    from shadow.store.models import Lesson, Segment
    with readonly_session(data_dir) as db:
        lesson = db.get(Lesson, lesson_id)
        if lesson is None or not lesson.transcript_json:
            raise SystemExit(f"lesson {lesson_id} not found or has no transcript")
        segs = db.exec(select(Segment).where(Segment.lesson_id == lesson_id).order_by(Segment.idx)).all()
        tr = Transcript.from_json(lesson.transcript_json)
    wav, sr = audio.read_wav(FileLayout(data_dir).source_wav(lesson_id))
    total = len(wav) / sr
    aligner = MmsAligner(device_for(half), int8=(half == "int8"))
    truth, onsets, prev_end = [], [], 0.0
    for s in segs:
        if s.char_from is None or s.char_to is None:
            continue
        chars = tr.chars[s.char_from:s.char_to + 1]
        speech = [c for c in chars if not is_punct(c.c)]
        if not speech:
            continue
        c0, c1 = speech[0].start, speech[-1].end
        truth.append(energy_onset(wav, sr, max(prev_end, c0 - 1.0), c1))
        prev_end = c1
        win = (max(0.0, chars[0].start - MARGIN_S), min(total, chars[-1].end + MARGIN_S))
        try:
            got = align_in_window(aligner, wav, sr, s.text, *win)
        except Exception as e:  # noqa: BLE001
            print(f"sentence {s.idx}: failed: {e}")
            got = []
        rep = clamp_spans(repair_spans(got, coarse_times(s.text, chars)), *win)
        onsets.append(rep[0].start if rep else None)
    out.write_text(json.dumps({"truth": truth, "onsets": onsets, "device": aligner.device}))
    print(f"{out.name}: {len(onsets)} sentences")


def align_report(lesson_id: int) -> bool | None:
    from shadow.ingest.aligncheck import onset_error
    fp, i8 = (load_json(cache_file(f"align-{h}-lesson{lesson_id}.json")) for h in ("fp32", "int8"))
    if fp is None or i8 is None:
        print("align: both halves are needed (missing:", [h for h, d in (("fp32", fp), ("int8", i8)) if d is None], ")")
        return None
    keep = [k for k, t in enumerate(fp["truth"]) if t is not None and fp["onsets"][k] is not None
            and i8["onsets"][k] is not None]
    e = {h: onset_error([d["onsets"][k] for k in keep], [d["truth"][k] for k in keep])
         for h, d in (("fp32", fp), ("int8", i8))}
    diff = e["int8"].mean_ms - e["fp32"].mean_ms
    for h in e:
        print(f"{h:5} n={e[h].n} mean {e[h].mean_ms} ms  median {e[h].median_ms} ms  within 100 ms {e[h].within_100ms}")
    ok = diff <= ONSET_MARGIN_MS
    print(f"align lesson {lesson_id}: int8 mean onset error minus fp32 = {diff:+.1f} ms (<= {ONSET_MARGIN_MS:.0f}): "
          f"{'PASS' if ok else 'FAIL'}")
    return ok


# ---- words ----

def words_half(half: str, data_dir: Path, limit: int | None) -> None:
    out = cache_file(f"words-{half}.json")
    if out.exists():
        print(f"{out.name}: cached")
        return
    from sqlmodel import select
    from shadow.config import load_settings
    from shadow.ingest.asr import ParaformerASR
    from shadow.scoring.reference import segment_syllables
    from shadow.store.models import Attempt, Segment
    settings = load_settings()
    asr = ParaformerASR(settings.models.asr, device_for(half), punctuation=False, int8=(half == "int8"))
    res: dict[str, dict] = {}
    with readonly_session(data_dir) as db:
        atts = db.exec(select(Attempt).where(Attempt.score_json != None).order_by(Attempt.id)).all()   # noqa: E711
        for n, att in enumerate(atts[:limit] if limit else atts, 1):
            wav = data_dir / "attempts" / f"{att.id}.wav"
            if not wav.exists():
                wav = Path(att.audio_path)
            seg = db.get(Segment, att.segment_id)
            if not wav.exists() or seg is None:
                continue
            syl = segment_syllables(seg)
            if not syl:
                continue
            heard = asr.transcribe(wav).text.strip()
            res[str(att.id)] = {"heard": heard, "syllables": [{"pinyin_toneless": s["pinyin_toneless"], "tone": s["tone"]}
                                                              for s in syl]}
            if n % 25 == 0:
                print(f"{half}: {n}/{len(atts)} takes", flush=True)
    out.write_text(json.dumps(res, ensure_ascii=False))
    print(f"{out.name}: {len(res)} takes")


def words_report() -> bool | None:
    from shadow.config import ScoringCfg
    from shadow.scoring.gate import text_similarity
    fp, i8 = load_json(cache_file("words-fp32.json")), load_json(cache_file("words-int8.json"))
    if fp is None or i8 is None:
        print("words: both halves are needed (missing:", [h for h, d in (("fp32", fp), ("int8", i8)) if d is None], ")")
        return None
    cfg = ScoringCfg()
    ids = sorted(set(fp) & set(i8), key=int)
    va, vb = [], []
    for k in ids:
        syl = fp[k]["syllables"]
        va.append(verdict_of(text_similarity(syl, fp[k]["heard"]), cfg.min_text_similarity, cfg.words_ok_at))
        vb.append(verdict_of(text_similarity(syl, i8[k]["heard"]), cfg.min_text_similarity, cfg.words_ok_at))
    share = agreement(va, vb)
    for v in ("clean", "some", "different"):
        print(f"{v:9} fp32 {va.count(v):4}  int8 {vb.count(v):4}")
    for k, a, b in zip(ids, va, vb):
        if a != b:
            print(f"  differs: take {k}: fp32 {a} ({fp[k]['heard']!r}) int8 {b} ({i8[k]['heard']!r})")
    ok = share >= AGREEMENT_MIN
    print(f"words: verdict agreement {share:.1%} over {len(ids)} takes (>= {AGREEMENT_MIN:.0%}): {'PASS' if ok else 'FAIL'}")
    return ok


# ---- cer ----

def cer_wavs() -> list[Path]:
    return sorted(GATE_CACHE.glob("*/source.wav"))


def cer_half(half: str) -> None:
    from shadow.config import load_settings
    from shadow.ingest.asr import ParaformerASR
    wavs = cer_wavs()
    if not wavs:
        raise SystemExit(f"no audio under {GATE_CACHE}: run split_gate.py first")
    settings = load_settings()
    asr = None
    for wav in wavs:
        out = cache_file(f"cer-{half}-{wav.parent.name}.json")
        if out.exists():
            print(f"{out.name}: cached")
            continue
        if asr is None:
            asr = ParaformerASR(settings.models.asr, device_for(half), punctuation=True, int8=(half == "int8"))
        print(f"transcribing {wav.parent.name} ({half}) ...", flush=True)
        out.write_text(json.dumps({"text": asr.transcribe(wav).text}, ensure_ascii=False))


def cer_report() -> bool | None:
    refs, hyps = [], []
    for wav in cer_wavs():
        fp, i8 = (load_json(cache_file(f"cer-{h}-{wav.parent.name}.json")) for h in ("fp32", "int8"))
        if fp is None or i8 is None:
            print(f"cer: {wav.parent.name} lacks a half")
            return None
        refs.append(fp["text"])
        hyps.append(i8["text"])
    if not refs:
        print("cer: no audio under", GATE_CACHE)
        return None
    c = cer(refs, hyps)
    ok = c <= CER_MAX
    print(f"cer: int8 vs fp32 over {len(refs)} sources, {sum(len(squash(r)) for r in refs)} characters: {c:.2%} "
          f"(<= {CER_MAX:.0%}): {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("check", choices=["align", "words", "cer"])
    ap.add_argument("--half", choices=["fp32", "int8", "report", "all"], default="all")
    ap.add_argument("--lesson", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None, help="words: only the first N takes")
    ap.add_argument("--data-dir", type=Path, default=None)
    a = ap.parse_args()
    from shadow.config import load_settings
    data_dir = a.data_dir or Path(load_settings().data_dir)
    verdict = None
    for h in halves(a.half):
        if h == "report":
            verdict = {"align": lambda: align_report(a.lesson), "words": words_report, "cer": cer_report}[a.check]()
        elif a.check == "align":
            align_half(h, a.lesson, data_dir)
        elif a.check == "words":
            words_half(h, data_dir, a.limit)
        else:
            cer_half(h)
        release()
    if verdict is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
