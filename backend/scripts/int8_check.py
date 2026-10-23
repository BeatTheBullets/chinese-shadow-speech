"""int8 validation: does the 8-bit recogniser / aligner give the same answers as fp32? (laptop-fit plan, Task 6)

    uv run python scripts/int8_check.py align --lesson 1 [--half fp32|int8|report]
    uv run python scripts/int8_check.py words [--half ...] [--limit N]
    uv run python scripts/int8_check.py cer   [--half ...]

Each check has two model halves, run in separate processes if memory is tight, and a report that needs no model:
  fp32   today's models (on the GPU when there is one), result cached as JSON
  int8   the 8-bit models on the CPU (run with CUDA_VISIBLE_DEVICES=""), result cached as JSON
  report compares the two cached files, prints the numbers and PASS or FAIL (default `all` runs the three in turn).
The fp32 half takes --device cpu|cuda (a CPU control for the GPU baseline). Cache files are keyed by check, variant
(fp32-cuda, fp32-cpu, int8-cpu), model, lesson/video and --limit. The report compares --a with --b (default: the fp32
half's device vs int8-cpu) and any extra --pair A:B, e.g.
    int8_check.py words --half report --a fp32-cuda --b fp32-cpu --pair fp32-cpu:int8-cpu
Only pairs ending in an int8 variant get PASS or FAIL; fp32 pairs are controls.
--data-dir (default: the settings' data dir) is only read; the database is opened read-only. Every cached result goes
under this checkout's .cache/scripts/int8-check/. CER also reads the audio cached by split_gate.py under
.cache/scripts/split-gate/ (run split_gate.py first so the gate's videos are there).

Pass marks: mean onset error within 10 ms of fp32; words-check verdict agreement >= 95 %; transcript CER <= 2 %."""
from __future__ import annotations
import argparse
import gc
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

CACHE = ROOT / ".cache" / "scripts" / "int8-check"
GATE_CACHE = ROOT / ".cache" / "scripts" / "split-gate"
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


def device_for(half: str, override: str | None = None) -> str:
    """int8 always runs on the CPU; fp32 on --device, else the GPU when there is one."""
    if half == "int8":
        return "cpu"
    if override:
        return override
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


def variant(half: str, device: str) -> str:
    """What produced a result: 'fp32-cuda', 'fp32-cpu', 'int8-cpu'."""
    return f"{half}-{device}"


def cache_key(check: str, var: str, *, model: str | None = None, lesson: int | None = None,
              video: str | None = None, limit: int | None = None) -> str:
    """Cache file name keyed by everything that shapes the result, so a control or limited run never reuses a file."""
    parts = [check, var]
    if model:
        parts.append(re.sub(r"[^A-Za-z0-9]+", "_", model.rsplit("/", 1)[-1])[:40])
    if lesson is not None:
        parts.append(f"lesson{lesson}")
    if video:
        parts.append(video)
    if limit:
        parts.append(f"limit{limit}")
    return "-".join(parts) + ".json"


def parse_pair(text: str) -> tuple[str, str]:
    a, _, b = text.partition(":")
    if not a or not b:
        raise ValueError(f"pair must look like fp32-cuda:int8-cpu, got {text!r}")
    return a, b


def compare_verdicts(verdicts: dict[str, list[str]], pairs: list[tuple[str, str]]) -> list[tuple[str, str, float]]:
    """Agreement share for each (a, b) pair of variants' verdict lists."""
    return [(a, b, agreement(verdicts[a], verdicts[b])) for a, b in pairs]


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

def align_half(half: str, lesson_id: int, data_dir: Path, device: str) -> None:
    out = cache_file(cache_key("align", variant(half, device), lesson=lesson_id))
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
    aligner = MmsAligner(device, int8=(half == "int8"))
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


def align_report(lesson_id: int, pairs: list[tuple[str, str]]) -> bool | None:
    from shadow.ingest.aligncheck import onset_error
    result: bool | None = None
    for a, b in pairs:
        da, db = (load_json(cache_file(cache_key("align", v, lesson=lesson_id))) for v in (a, b))
        if da is None or db is None:
            print(f"align {a} vs {b}: missing", [v for v, d in ((a, da), (b, db)) if d is None])
            continue
        keep = [k for k, t in enumerate(da["truth"]) if t is not None and da["onsets"][k] is not None
                and db["onsets"][k] is not None]
        e = {v: onset_error([d["onsets"][k] for k in keep], [d["truth"][k] for k in keep]) for v, d in ((a, da), (b, db))}
        diff = e[b].mean_ms - e[a].mean_ms
        for v in (a, b):
            print(f"{v:10} n={e[v].n} mean {e[v].mean_ms} ms  median {e[v].median_ms} ms  within 100 ms {e[v].within_100ms}")
        if b.startswith("int8"):
            ok = diff <= ONSET_MARGIN_MS
            print(f"align lesson {lesson_id}: {b} minus {a} = {diff:+.1f} ms (<= {ONSET_MARGIN_MS:.0f}): {'PASS' if ok else 'FAIL'}")
            result = ok if result is None else (result and ok)
        else:
            print(f"align lesson {lesson_id}: {b} minus {a} = {diff:+.1f} ms (control, no pass mark)")
    return result


# ---- words ----

def words_half(half: str, data_dir: Path, limit: int | None, device: str) -> None:
    from shadow.config import load_settings as _ls
    out = cache_file(cache_key("words", variant(half, device), model=_ls().models.asr, limit=limit))
    if out.exists():
        print(f"{out.name}: cached")
        return
    from sqlmodel import select
    from shadow.config import load_settings
    from shadow.ingest.asr import ParaformerASR
    from shadow.scoring.reference import segment_syllables
    from shadow.store.models import Attempt, Segment
    settings = load_settings()
    asr = ParaformerASR(settings.models.asr, device, int8=(half == "int8"))
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


def words_report(pairs: list[tuple[str, str]], limit: int | None) -> bool | None:
    from shadow.config import ScoringCfg, load_settings
    from shadow.scoring.gate import text_similarity
    cfg, model = ScoringCfg(), load_settings().models.asr
    data = {v: load_json(cache_file(cache_key("words", v, model=model, limit=limit))) for v in {x for p in pairs for x in p}}
    result: bool | None = None
    for a, b in pairs:
        if data[a] is None or data[b] is None:
            print(f"words {a} vs {b}: missing", [v for v in (a, b) if data[v] is None])
            continue
        ids = sorted(set(data[a]) & set(data[b]), key=int)
        verd = {v: [verdict_of(text_similarity(data[a][k]["syllables"], data[v][k]["heard"]), cfg.min_text_similarity,
                               cfg.words_ok_at) for k in ids] for v in (a, b)}
        share = compare_verdicts(verd, [(a, b)])[0][2]
        for w in ("clean", "some", "different"):
            print(f"{w:9} {a} {verd[a].count(w):4}  {b} {verd[b].count(w):4}")
        for k, x, y in zip(ids, verd[a], verd[b]):
            if x != y:
                print(f"  differs: take {k}: {a} {x} ({data[a][k]['heard']!r}) {b} {y} ({data[b][k]['heard']!r})")
        if b.startswith("int8"):
            ok = share >= AGREEMENT_MIN
            print(f"words: {a} vs {b} verdict agreement {share:.1%} over {len(ids)} takes (>= {AGREEMENT_MIN:.0%}): "
                  f"{'PASS' if ok else 'FAIL'}")
            result = ok if result is None else (result and ok)
        else:
            print(f"words: {a} vs {b} verdict agreement {share:.1%} over {len(ids)} takes (control, no pass mark)")
    return result


# ---- cer ----

def cer_wavs() -> list[Path]:
    return sorted(GATE_CACHE.glob("*/source.wav"))


def cer_half(half: str, device: str) -> None:
    from shadow.config import load_settings
    from shadow.ingest.asr import ParaformerASR
    wavs = cer_wavs()
    if not wavs:
        raise SystemExit(f"no audio under {GATE_CACHE}: run split_gate.py first")
    settings = load_settings()
    asr = None
    for wav in wavs:
        out = cache_file(cache_key("cer", variant(half, device), model=settings.models.asr, video=wav.parent.name))
        if out.exists():
            print(f"{out.name}: cached")
            continue
        if asr is None:
            from shadow.ingest.punct import make_punctuator
            asr = ParaformerASR(settings.models.asr, device, punctuator=make_punctuator(settings.models),
                                segmentation=settings.segmentation, int8=(half == "int8"))
        print(f"transcribing {wav.parent.name} ({half}) ...", flush=True)
        out.write_text(json.dumps({"text": asr.transcribe(wav).text}, ensure_ascii=False))


def cer_report(pairs: list[tuple[str, str]]) -> bool | None:
    from shadow.config import load_settings
    model = load_settings().models.asr
    result: bool | None = None
    for a, b in pairs:
        refs, hyps, missing = [], [], False
        for wav in cer_wavs():
            da, db = (load_json(cache_file(cache_key("cer", v, model=model, video=wav.parent.name))) for v in (a, b))
            if da is None or db is None:
                print(f"cer {a} vs {b}: {wav.parent.name} lacks a half")
                missing = True
                break
            refs.append(da["text"])
            hyps.append(db["text"])
        if missing or not refs:
            continue
        c = cer(refs, hyps)
        n = sum(len(squash(r)) for r in refs)
        if b.startswith("int8"):
            ok = c <= CER_MAX
            print(f"cer: {b} vs {a} over {len(refs)} sources, {n} characters: {c:.2%} (<= {CER_MAX:.0%}): {'PASS' if ok else 'FAIL'}")
            result = ok if result is None else (result and ok)
        else:
            print(f"cer: {b} vs {a} over {len(refs)} sources, {n} characters: {c:.2%} (control, no pass mark)")
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("check", choices=["align", "words", "cer"])
    ap.add_argument("--half", choices=["fp32", "int8", "report", "all"], default="all")
    ap.add_argument("--device", choices=["cpu", "cuda"], default=None, help="fp32 half: device (default: GPU if any)")
    ap.add_argument("--a", default=None, help="report: first variant, e.g. fp32-cuda (default: the fp32 half's default)")
    ap.add_argument("--b", default="int8-cpu", help="report: second variant, e.g. fp32-cpu or int8-cpu")
    ap.add_argument("--pair", action="append", default=[], metavar="A:B", help="report: another pair to compare")
    ap.add_argument("--lesson", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None, help="words: only the first N takes")
    ap.add_argument("--data-dir", type=Path, default=None)
    a = ap.parse_args()
    from shadow.config import load_settings
    from shadow.memory import release_freed_memory_eagerly
    release_freed_memory_eagerly()      # before any model loads
    data_dir = a.data_dir or Path(load_settings().data_dir)
    pairs = [(a.a or variant("fp32", device_for("fp32", a.device)), a.b)] + [parse_pair(p) for p in a.pair]
    verdict = None
    for h in halves(a.half):
        dev = device_for(h, a.device)
        if h == "report":
            verdict = {"align": lambda: align_report(a.lesson, pairs), "words": lambda: words_report(pairs, a.limit),
                       "cer": lambda: cer_report(pairs)}[a.check]()
        elif a.check == "align":
            align_half(h, a.lesson, data_dir, dev)
        elif a.check == "words":
            words_half(h, data_dir, a.limit, dev)
        else:
            cer_half(h, dev)
        release()
    if verdict is False:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
