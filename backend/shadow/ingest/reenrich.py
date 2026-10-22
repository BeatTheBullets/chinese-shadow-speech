"""Re-processing of single segments after a manual edit (text change, resplit, merge)."""
from __future__ import annotations
from pathlib import Path
from sqlalchemy import Engine
from sqlmodel import Session, select
from shadow.deps import Deps
from shadow.ingest import audio
from shadow.ingest.align import sentence_bounds, spans_to_json
from shadow.ingest.enrich import make_clips, words_for
from shadow.ingest.pipeline import MIN_CLIP_S, WINDOW_MARGIN_S, _align
from shadow.ingest.repair import Times, clamp_spans, coarse_times, repair_spans
from shadow.ingest.transcript import Transcript
from shadow.store.models import Lesson, Segment


def _neighbours(db: Session, seg: Segment, total: float) -> tuple[float, float]:
    """(previous segment's end, next segment's start), or the audio's edges."""
    prev = db.exec(select(Segment).where(Segment.lesson_id == seg.lesson_id, Segment.idx == seg.idx - 1)).first()
    nxt = db.exec(select(Segment).where(Segment.lesson_id == seg.lesson_id, Segment.idx == seg.idx + 1)).first()
    return (prev.end_s if prev else 0.0, nxt.start_s if nxt else total)


def _unlink(*paths: Path) -> None:
    for p in paths:
        p.unlink(missing_ok=True)


def _coarse(lesson: Lesson, seg: Segment, window: tuple[float, float]) -> list[Times | None] | None:
    """Coarse char times for the re-aligned `seg.text` (addendum §1.1): its transcript char range, or, for a segment
    that lost it in a resplit, the transcript chars starting inside the alignment window. None without a transcript
    (Anki lessons)."""
    if lesson.source_type == "anki" or not lesson.transcript_json:
        return None
    chars = Transcript.from_json(lesson.transcript_json).chars
    if seg.char_from is not None and seg.char_to is not None:
        chars = chars[seg.char_from:seg.char_to + 1]
    else:
        chars = [c for c in chars if window[0] <= c.start <= window[1]]
    return coarse_times(seg.text, chars)


def reenrich_segment(deps: Deps, engine: Engine, segment_id: int, window: tuple[float, float] | None = None,
                     text: str | None = None) -> None:
    """Re-align `seg.text` (or the new `text`), rebuild words and clips and clear the translation (spec §4: an
    edit re-runs align + enrich). All or nothing: the text and its enrichment are committed together, and clip
    files are only replaced once both are encoded, so a failure leaves the segment and its clips as they were.

    Upload lessons: aligned inside `window` (default: the segment's span ±1 s); the clip becomes the padded
    alignment clamped to the neighbouring segments, or keeps its bounds when alignment finds nothing.
    Anki lessons: the segment's span is the note's audio, so it is aligned inside `window` (default: that span)
    and its bounds are left as they are."""
    with Session(engine) as db:
        seg = db.get(Segment, segment_id)
        if text is not None:
            seg.text = text
        lesson = db.get(Lesson, seg.lesson_id)
        fixed = lesson.source_type == "anki"
        source = deps.files.source_wav(seg.lesson_id)
        wav, sr = audio.read_wav(source)
        total = len(wav) / sr
        if window is None:
            window = (seg.start_s, seg.end_s) if fixed else \
                (max(0.0, seg.start_s - WINDOW_MARGIN_S), min(total, seg.end_s + WINDOW_MARGIN_S))
        spans = repair_spans(_align(deps, wav, sr, seg.idx, seg.text, *window), _coarse(lesson, seg, window))
        spans = clamp_spans(spans, window[0], min(window[1], total))
        if spans and not fixed:
            pad = deps.settings.segmentation.pad_ms / 1000
            start, end = sentence_bounds(spans, pad, *_neighbours(db, seg, total), total)
            if end - start < MIN_CLIP_S:          # neighbours aligned on top of it: own padded envelope
                start, end = round(max(spans[0].start - pad, 0.0), 3), round(min(spans[-1].end + pad, total), 3)
            if end - start >= MIN_CLIP_S:
                seg.start_s, seg.end_s = start, end
        seg.ref_alignment_json = spans_to_json(spans)
        seg.words_json = words_for(seg.text)
        seg.translation = None
        wav_p, opus_p = make_clips(deps.files, seg.lesson_id, seg.idx, source, seg.start_s, seg.end_s)
        seg.clip_wav_path, seg.clip_opus_path = str(wav_p), str(opus_p)
        _unlink(deps.files.clip_mp3(seg.lesson_id, seg.idx))      # rendered lazily from the new wav
        db.add(seg); db.commit()


def _move_clips(deps: Deps, seg: Segment, new_idx: int, staged: list[tuple[Path, Path]] | None = None) -> None:
    """Point `seg`'s clips at `new_idx` (renaming the files) and drop the mp3s at both indices. With `staged`,
    files go to a temporary name first and (temp, final) pairs are appended for the caller to finish."""
    files, lid = deps.files, seg.lesson_id
    targets = (files.clip_wav(lid, new_idx), files.clip_opus(lid, new_idx))
    for old, new in zip((seg.clip_wav_path, seg.clip_opus_path), targets):
        if old and Path(old) != new and Path(old).exists():
            if staged is None:
                Path(old).rename(new)
            else:
                tmp = new.with_name(new.name + ".tmp")
                Path(old).rename(tmp); staged.append((tmp, new))
    _unlink(files.clip_mp3(lid, seg.idx), files.clip_mp3(lid, new_idx))
    seg.idx = new_idx
    seg.clip_wav_path, seg.clip_opus_path = (str(t) for t in targets)


def shift_after(deps: Deps, db: Session, lesson_id: int, idx: int, delta: int) -> None:
    """Move every segment after `idx` by `delta` positions, clip files included (caller commits).
    The `delta` slots the segments move into must be free."""
    later = db.exec(select(Segment).where(Segment.lesson_id == lesson_id, Segment.idx > idx)
                    .order_by(Segment.idx.desc() if delta > 0 else Segment.idx)).all()
    for seg in later:                   # far end first when moving up, near end first when moving down
        _move_clips(deps, seg, seg.idx + delta)
        db.add(seg)


def renumber(deps: Deps, engine: Engine, lesson_id: int) -> None:
    """Make idx dense (0..n-1), keeping the current order, with every segment's clips at its own idx.
    (Order is by idx, not time: overlapping clips may start out of order, and text order must not change.)"""
    with Session(engine) as db:
        segs = db.exec(select(Segment).where(Segment.lesson_id == lesson_id).order_by(Segment.idx, Segment.start_s)).all()
        staged: list[tuple[Path, Path]] = []
        for new_idx, seg in enumerate(segs):
            expected = (str(deps.files.clip_wav(lesson_id, new_idx)), str(deps.files.clip_opus(lesson_id, new_idx)))
            if seg.idx != new_idx or (seg.clip_wav_path, seg.clip_opus_path) != expected:
                _move_clips(deps, seg, new_idx, staged)
                db.add(seg)
        for tmp, new in staged:
            tmp.rename(new)
        db.commit()
