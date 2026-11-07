"""Tone scoring of an attempt (Phase 2 spec §1): the database side around the pure `score_take`."""
from __future__ import annotations
import logging
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING
from sqlmodel import Session
from shadow.ingest import audio
from shadow.scoring.profile import add_frames, get_profile, profile_baseline
from shadow.scoring.reference import (lesson_baseline, reference_audio, reference_embeddings, reference_pitch,
                                     reference_spans, segment_syllables, sound_ref_key)
from shadow.scoring.score import RefData, failed_result, score_take
from shadow.store.models import Attempt, Lesson, Segment, SyllableScore

if TYPE_CHECKING:                        # shadow.deps imports shadow.scoring.tone: avoid the cycle at runtime
    from shadow.deps import Deps

log = logging.getLogger(__name__)


def _hear(deps: Deps, attempt: Attempt) -> str | None:
    heard = deps.hearer.hear(Path(attempt.audio_path))
    if heard is None:
        log.info("attempt %s: the recogniser is busy (an import?), words check skipped", attempt.id)
    return heard


def _drop_failed_sounds(deps: Deps) -> None:
    """A sounds model whose (lazy) load failed switches sounds off for this process and shows on /health, so the
    failing load is not retried on every take."""
    chars = getattr(deps.sounds, "chars", None)
    if chars is not None and getattr(chars, "_model", True) is None and getattr(chars, "load_error", None):
        deps.sounds_error = chars.load_error
        deps.sounds = None


def score_attempt(deps: Deps, db: Session, segment: Segment, attempt: Attempt) -> None:
    """Sets attempt.score_json, adds its SyllableScore rows and feeds the voice profile. Never raises: a failure
    leaves `overall: null` with a warning and no rows (spec §7). The caller has committed the attempt (its audio)
    and anything else pending, since a failure rolls the session back, and commits afterwards.

    SQLite has one writer: a flushed write holds the database lock until the commit, and scoring can take minutes
    (the first-ever take downloads the embedder, the first of a lesson tracks pitch over every clip). So the reads
    run without autoflush and every write (the lesson's cached baseline included) stays pending until the flush at
    the end, which the caller's commit follows at once."""
    cfg = deps.settings.scoring
    syllables = segment_syllables(segment)
    try:
        with db.no_autoflush:
            ref_pitch = reference_pitch(deps.files, cfg, segment)
            lesson = db.get(Lesson, segment.lesson_id)
            ref_base = lesson_baseline(deps.files, cfg, db, lesson) if ref_pitch is not None and lesson else None
            prof = get_profile(db)
            if ref_pitch is None or ref_base is None or not segment.ref_alignment_json:
                result = failed_result(syllables, ["no_reference"])
            elif deps.embedder is None:
                result = failed_result(syllables, ["no_tone_model"])
            else:
                wav, sr = audio.read_wav(Path(attempt.audio_path))
                ref_key = sound_ref_key(segment, syllables)
                ref_wav, ref_sr = reference_audio(segment)
                ref = RefData(ref_pitch, reference_spans(segment), ref_base, ref_wav, ref_sr,
                              pooled=partial(reference_embeddings, deps.files, deps.embedder, segment, ref_wav, ref_sr))
                result = score_take(ref=ref, syllables=syllables, text=segment.text, wav=wav, sr=sr,
                                    aligner=deps.aligner, embedder=deps.embedder, model=deps.tone_model,
                                    profile=profile_baseline(prof), profile_voiced_s=prof.voiced_s or 0.0, cfg=cfg,
                                    hear=(lambda: _hear(deps, attempt)) if deps.hearer else None,
                                    sounds=deps.sounds, ref_key=ref_key)
                _drop_failed_sounds(deps)
            attempt.score_json = result.json
            for row in result.rows:
                db.add(SyllableScore(attempt_id=attempt.id, segment_id=segment.id, **row))
            if result.rows:
                add_frames(db, prof, result.voiced_f0)
        db.flush()                       # inside the try: a failing write is a failed score, not a lost take
    except Exception:
        log.exception("scoring attempt %s failed", attempt.id)
        db.rollback()                    # drop the half-written score so the caller's commit still saves the take
        attempt.score_json = failed_result(syllables, ["score_failed"]).json
