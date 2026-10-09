"""The reference side of scoring (Phase 2 spec §1 step 4, §2): cached clip pitch, spans and the lesson baseline."""
from __future__ import annotations
from pathlib import Path
import numpy as np
from sqlmodel import Session, select
from shadow.config import ScoringCfg
from shadow.ingest import audio
from shadow.scoring.pitch import Baseline, Pitch, baseline_of, track_pitch
from shadow.store.files import FileLayout
from shadow.store.models import Lesson, Segment


def segment_syllables(seg: Segment) -> list[dict]:
    return [s for w in (seg.words_json or []) for s in w.get("syllables", [])]


def reference_spans(seg: Segment) -> list[tuple[float, float]]:
    """Alignment spans are on the lesson's time axis; the clip starts at the segment's start_s."""
    return [(a["start"] - seg.start_s, a["end"] - seg.start_s) for a in (seg.ref_alignment_json or [])]


def reference_pitch(files: FileLayout, cfg: ScoringCfg, seg: Segment) -> Pitch | None:
    """The clip's pitch, cached per clip file version (an edit re-cuts the clip, so its mtime changes)."""
    if not seg.clip_wav_path or not Path(seg.clip_wav_path).exists():
        return None
    clip = Path(seg.clip_wav_path)
    cache = files.cache_dir("f0") / f"{seg.id}-{clip.stat().st_mtime_ns}.npz"
    if cache.exists():
        d = np.load(cache)
        return Pitch(float(d["t0"]), d["f0"])
    wav, sr = audio.read_wav(clip)
    p = track_pitch(wav, sr, cfg.f0_floor, cfg.f0_ceiling)
    np.savez(cache, t0=p.t0, f0=p.f0)
    return p


def lesson_baseline(files: FileLayout, cfg: ScoringCfg, db: Session, lesson: Lesson) -> Baseline | None:
    """The speaker over every clip of the lesson, computed once and kept in meta_json["pitch"] (spec §2)."""
    meta = lesson.meta_json or {}
    if "pitch" in meta:
        return Baseline(meta["pitch"]["baseline_hz"], meta["pitch"]["spread_st"])
    segs = db.exec(select(Segment).where(Segment.lesson_id == lesson.id)).all()
    voiced = [p.voiced() for p in (reference_pitch(files, cfg, s) for s in segs) if p is not None]
    allv = np.concatenate(voiced) if voiced else np.zeros(0)
    b = baseline_of(allv)
    if b is None:
        return None
    lesson.meta_json = {**meta, "pitch": {"baseline_hz": b.hz, "spread_st": b.spread_st, "frames": int(len(allv))}}
    db.add(lesson)
    return b
