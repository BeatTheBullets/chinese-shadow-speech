"""Sentence-splitting gate: is splitting on pauses at least as good as splitting on punctuation?

    uv run python scripts/split_gate.py [--lessons 1 2 3 4] [--data-dir DIR] --out ../data/reports/split-gate.md

Sources: the YouTube videos in split_gate_urls.txt (human subtitles are the reference; the app's own subtitle alignment
times them) and, with --lessons, stored lessons (their stored segment boundaries are the reference). Each source is
transcribed once with the punctuation model on; candidate "punctuation" is today's rectify_transcript, candidate
"pauses" is pause_ranges over the same characters with punctuation removed. --data-dir (default: the settings' data dir)
is only read, and the lessons database is opened read-only; downloads and transcripts are cached under this checkout's
data/cache/split-gate/. --int8 transcribes with the 8-bit recogniser on the CPU (transcripts cached as asr-int8.json). Prints and writes a markdown report ending in PASS or FAIL."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from shadow.config import load_settings
from shadow.ingest import audio
from shadow.ingest.asr import ParaformerASR
from shadow.ingest.pauses import pause_ranges
from shadow.ingest.pipeline import _subtitle_transcript
from shadow.ingest.rectify import rectify_transcript
from shadow.ingest.splitcheck import SplitReport, gate_passes, match, piece_ends, reference_breaks, split_report
from shadow.ingest.text import is_punct
from shadow.ingest.transcript import TimedChar, Transcript
from shadow.ingest.youtube import YtDlpDownloader, choose_subtitle, parse_video_id, watch_url
from shadow.memory import release_freed_memory_eagerly

URLS = Path(__file__).with_name("split_gate_urls.txt")
CACHE = ROOT / "data" / "cache" / "split-gate"
SAMPLE = 15


class Source:
    def __init__(self, name: str, tr: Transcript, ref_all: list[float], ref_ends: list[float], minutes: float):
        self.name, self.tr, self.ref_all, self.ref_ends, self.minutes = name, tr, ref_all, ref_ends, minutes


def urls() -> list[str]:
    out = []
    for line in URLS.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def video_source(url: str, asr: ParaformerASR, int8: bool = False) -> Source | None:
    vid = parse_video_id(url)
    if vid is None:
        print(f"skip {url}: not a YouTube link")
        return None
    d = CACHE / vid
    d.mkdir(parents=True, exist_ok=True)
    dl = YtDlpDownloader()
    info = dl.probe(url)
    choice = choose_subtitle(info)
    if choice is None or choice.auto:
        print(f"skip {vid}: no uploaded Chinese subtitles ({sorted(info.subtitles)})")
        return None
    sub_path = d / f"subtitle.{choice.lang}.{choice.ext}"
    if not sub_path.exists():
        sub_path.write_text(dl.fetch_subtitle(url, choice), encoding="utf-8")
    wav = d / "source.wav"
    if not wav.exists():
        media = next((p for p in d.glob("audio.*")), None) or dl.download_audio(url, d)
        audio.normalise(media, wav)
    tr_path = d / ("asr-int8.json" if int8 else "asr.json")        # int8 transcripts never replace the fp32 ones
    if tr_path.exists():
        tr = Transcript.from_json(json.loads(tr_path.read_text()))
    else:
        print(f"transcribing {vid} ...", flush=True)
        tr = asr.transcribe(wav)
        tr_path.write_text(json.dumps(tr.to_json()))
    sub_tr, meta = _subtitle_transcript((sub_path.name, sub_path.read_text(encoding="utf-8")), tr)
    if sub_tr is None:
        print(f"skip {vid}: {meta}")
        return None
    ref_all, ref_ends = reference_breaks(sub_tr)
    return Source(f"{vid} ({choice.lang}, match {meta.get('subtitle_match')})", tr, ref_all, ref_ends,
                  audio.duration_s(wav) / 60)


def lesson_sources(data_dir: Path, ids: list[int]) -> list[Source]:
    from sqlalchemy import create_engine
    from sqlmodel import Session, select
    from shadow.store.models import Lesson, Segment
    db = data_dir / "shadow.db"
    if not db.exists():
        raise SystemExit(f"no database at {db}")
    engine = create_engine(f"sqlite:///file:{db}?mode=ro&uri=true")      # read-only: never writes the user's data
    out = []
    with Session(engine) as s:
        for lid in ids:
            lesson = s.get(Lesson, lid)
            if lesson is None or not lesson.transcript_json:
                print(f"skip lesson {lid}: not found or no transcript")
                continue
            tr = Transcript.from_json(lesson.transcript_json)
            segs = sorted(s.exec(select(Segment).where(Segment.lesson_id == lid)).all(), key=lambda g: g.idx)
            ends = []
            for g in segs[:-1]:
                if g.char_to is None:
                    continue
                k = g.char_to
                while k >= 0 and is_punct(tr.chars[k].c):
                    k -= 1
                if k >= 0:
                    ends.append(tr.chars[k].end)
            out.append(Source(f"lesson {lid}", tr, ends, ends, lesson.duration_s / 60))
    return out


def evaluate(src: Source, cfg) -> tuple[SplitReport, SplitReport, list[str], list[str]]:
    tr = src.tr
    punc_ranges = [(s.char_from, s.char_to) for s in rectify_transcript(tr)]
    speech = [c for c in tr.chars if not is_punct(c.c)]
    pause_r = pause_ranges(speech, cfg)
    punc = split_report(tr.chars, punc_ranges, src.ref_all, src.ref_ends)
    pauses = split_report(speech, pause_r, src.ref_all, src.ref_ends)
    return (punc, pauses, pieces(tr.chars, punc_ranges), pieces(speech, pause_r))


def pieces(chars: list[TimedChar], ranges: list[tuple[int, int]]) -> list[str]:
    return ["".join(c.c for c in chars[a:b + 1]) for a, b in ranges[:SAMPLE]]


def row(name: str, who: str, r: SplitReport) -> str:
    return (f"| {name} | {who} | {r.precision:.3f} | {r.recall:.3f} | {r.f1:.3f} | {r.end_recall:.3f} | {r.pieces} | "
            f"{r.over_25} | {r.over_30} | {r.under_4} | {r.inside_word} |")


HEADER = ("| source | splitter | precision | recall | F1 | end recall | pieces | >25 | >30 | <4 | inside word |\n"
          "|---|---|---|---|---|---|---|---|---|---|---|")


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--lessons", type=int, nargs="*", default=[])
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--int8", action="store_true", help="transcribe with the 8-bit recogniser on the CPU")
    a = ap.parse_args()
    release_freed_memory_eagerly()      # before any model loads
    settings = load_settings()
    data_dir = a.data_dir or Path(settings.data_dir)

    sources = lesson_sources(data_dir, a.lessons) if a.lessons else []
    device = "cpu" if a.int8 else settings.resolved_device()
    asr = ParaformerASR(settings.models.asr, device, punctuation=True, int8=a.int8)
    videos = [s for u in urls() if (s := video_source(u, asr, a.int8)) is not None]
    sources = videos + sources
    if not sources:
        raise SystemExit("no usable sources")

    lines = ["# Sentence-splitting gate", "", HEADER]
    pooled: dict[str, list[list]] = {"punctuation": [], "pauses": []}
    samples = []
    for i, src in enumerate(sources):
        punc, pauses, sp, sq = evaluate(src, settings.segmentation)
        lines += [row(src.name, "punctuation", punc), row(src.name, "pauses", pauses)]
        pooled["punctuation"].append([punc, src])
        pooled["pauses"].append([pauses, src])
        if i < 2 and src in videos:
            samples.append((src.name, sp, sq))
    seg = settings.segmentation
    only_videos = [k for k, src in enumerate(sources) if src in videos]

    def totals(label: str, which: list[int]) -> tuple[SplitReport, SplitReport]:
        tp = pool([pooled["punctuation"][k] for k in which], seg, "punctuation")
        tq = pool([pooled["pauses"][k] for k in which], seg, "pauses")
        lines.extend([row(label, "punctuation", tp), row(label, "pauses", tq)])
        return tp, tq

    # Stored lessons were split by punctuation, so their reference favours it: the verdict uses the videos' human
    # subtitles when there are any, and the all-sources total is shown for information.
    if videos and lessons_present(sources, videos):
        totals("TOTAL (all sources, lessons favour punctuation)", list(range(len(sources))))
    tp, tq = totals("TOTAL (videos)" if videos else "TOTAL", only_videos or list(range(len(sources))))
    lines.append("")
    minutes = sum(s.minutes for s in sources)
    verdict = "PASS" if gate_passes(tp, tq) else "FAIL"
    lines += [f"Audio: {minutes:.1f} minutes over {len(sources)} sources.", "",
              f"Gate (pauses F1 >= punctuation F1, pauses end recall >= punctuation end recall, no pause piece over 30 "
              f"characters): **{verdict}**", ""]
    for name, sp, sq in samples:
        lines += [f"## First {SAMPLE} pieces: {name}", "", "punctuation:"] + [f"{n + 1}. {t}" for n, t in enumerate(sp)]
        lines += ["", "pauses:"] + [f"{n + 1}. {t}" for n, t in enumerate(sq)] + [""]
    text = "\n".join(lines) + "\n"
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(text, encoding="utf-8")
    print(text)
    print(verdict)


def lessons_present(sources: list, videos: list) -> bool:
    return len(sources) > len(videos)


def pool(items: list[list], cfg, which: str) -> SplitReport:
    """One SplitReport over all sources together: every source's cuts and breaks are matched separately and the
    counts summed, so long sources weigh more."""
    tp = fp = fn = etp = efn = 0
    pieces_n = o25 = o30 = u4 = inside = 0
    for rep, src in items:
        tr = src.tr
        if which == "punctuation":
            chars = tr.chars
            ranges = [(s.char_from, s.char_to) for s in rectify_transcript(tr)]
        else:
            chars = [c for c in tr.chars if not is_punct(c.c)]
            ranges = pause_ranges(chars, cfg)
        pred = piece_ends(chars, ranges)
        a, b, c = match(pred, src.ref_all)
        tp, fp, fn = tp + a, fp + b, fn + c
        d, _, f = match(pred, src.ref_ends)
        etp, efn = etp + d, efn + f
        pieces_n += rep.pieces
        o25, o30, u4, inside = o25 + rep.over_25, o30 + rep.over_30, u4 + rep.under_4, inside + rep.inside_word
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return SplitReport(precision, recall, f1, etp / (etp + efn) if etp + efn else 0.0, pieces_n, o25, o30, u4, inside)


if __name__ == "__main__":
    main()
