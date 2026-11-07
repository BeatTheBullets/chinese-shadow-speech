"""The reference side of scoring (Phase 2 spec §1 step 4, §2): cached clip pitch, spans and the lesson baseline."""
from __future__ import annotations
import hashlib
import logging
import os
import uuid
from pathlib import Path
import numpy as np
from sqlmodel import Session, select
from shadow.config import ScoringCfg
from shadow.ingest import audio
from shadow.scoring.embed import Embedder, pool
from shadow.scoring.features import FEATURE_VERSION
from shadow.scoring.pitch import Baseline, Pitch, baseline_of, track_pitch
from shadow.store.files import FileLayout
from shadow.store.models import Lesson, Segment

log = logging.getLogger(__name__)
EMB_CACHE_VERSION = 1                     # bump when what the embedding cache holds, or how it is computed, changes


def segment_syllables(seg: Segment) -> list[dict]:
    return [s for w in (seg.words_json or []) for s in w.get("syllables", [])]


def sound_ref_key(seg: Segment, syllables: list[dict]) -> str:
    """The sound detector caches the reference's side by this key. The clip's mtime is in it (0 when missing): a
    rebuild re-cuts the clip at the same path, and must not reuse the old clip's reference GOPs."""
    clip = Path(seg.clip_wav_path) if seg.clip_wav_path else None
    mtime = clip.stat().st_mtime_ns if clip is not None and clip.exists() else 0
    return f"{seg.clip_wav_path}|{seg.text}|" + " ".join(s["pinyin_toneless"] for s in syllables) + f"|{mtime}"


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


def reference_embeddings(files: FileLayout, embedder: Embedder, seg: Segment, wav: np.ndarray, sr: int,
                         win: list[tuple[float, float]]) -> np.ndarray:
    """The clip's speech-model embeddings pooled over its syllable windows, exactly as scoring computes them, cached
    on disk: the clip is the same for every take of a segment, so its model pass runs once, not per take. The file
    is per clip version (mtime: an edit re-cuts the clip) and per hash of everything the value depends on (samples,
    windows, embedder model, revision, layer and device, the feature and cache versions)."""
    clip = Path(seg.clip_wav_path) if seg.clip_wav_path else None
    mtime = clip.stat().st_mtime_ns if clip is not None and clip.exists() else 0
    x = np.ascontiguousarray(wav)
    ident = [type(embedder).__qualname__, *(str(getattr(embedder, k, "")) for k in ("name", "revision", "layer", "device")),
             f"f{FEATURE_VERSION}", f"c{EMB_CACHE_VERSION}", str(sr), x.dtype.str, str(x.shape)]
    h = hashlib.sha256("|".join(ident).encode())
    h.update(x.tobytes())
    h.update(np.asarray(win, np.float64).tobytes())
    cache = files.cache_dir("emb") / f"{seg.id}-{mtime}-{h.hexdigest()[:24]}.npy"
    try:
        got = np.load(cache, allow_pickle=False)
        if got.ndim == 2 and got.shape[0] == len(win) and got.dtype == np.float32:
            return got
    except FileNotFoundError:
        pass
    except Exception:  # noqa: BLE001
        log.warning("unreadable embedding cache %s; recomputing it", cache.name, exc_info=True)
    out = pool(embedder.frames(wav, sr), win)
    tmp = cache.with_name(f".{cache.name}.{uuid.uuid4().hex}.tmp")
    try:                                  # written aside and renamed: a concurrent take never reads half a file
        with open(tmp, "wb") as f:
            np.save(f, out)
        os.replace(tmp, cache)
    except OSError:
        log.warning("could not cache the reference embeddings in %s", cache.name, exc_info=True)
        tmp.unlink(missing_ok=True)
    return out


def reference_audio(seg: Segment) -> tuple[np.ndarray, int]:
    return audio.read_wav(Path(seg.clip_wav_path))


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
