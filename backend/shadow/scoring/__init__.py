"""Tone scoring of an attempt (Phase 2 spec §1): the database side around the pure `score_take`."""
from __future__ import annotations
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from sqlmodel import Session
from shadow.ingest import audio
from shadow.scoring.profile import add_frames, get_profile, profile_baseline
from shadow.scoring.reference import lesson_baseline, reference_pitch, reference_spans, segment_syllables
from shadow.scoring.score import RefData, failed_result, score_take
from shadow.store.models import Attempt, Lesson, Segment, SyllableScore

if TYPE_CHECKING:                        # shadow.deps imports shadow.scoring.tone: avoid the cycle at runtime
    from shadow.deps import Deps

log = logging.getLogger(__name__)


def score_attempt(deps: Deps, db: Session, segment: Segment, attempt: Attempt) -> None:
    """Sets attempt.score_json, adds its SyllableScore rows and feeds the voice profile. Never raises: a failure
    leaves `overall: null` with a warning and no rows (spec §7). The caller commits."""
    cfg = deps.settings.scoring
    syllables = segment_syllables(segment)
    try:
        ref_pitch = reference_pitch(deps.files, cfg, segment)
        lesson = db.get(Lesson, segment.lesson_id)
        ref_base = lesson_baseline(deps.files, cfg, db, lesson) if ref_pitch is not None and lesson else None
        if ref_pitch is None or ref_base is None or not segment.ref_alignment_json:
            result = failed_result(syllables, ["no_reference"])
        else:
            prof = get_profile(db)
            wav, sr = audio.read_wav(Path(attempt.audio_path))
            result = score_take(ref=RefData(ref_pitch, reference_spans(segment), ref_base), syllables=syllables,
                                text=segment.text, wav=wav, sr=sr, aligner=deps.aligner, model=deps.tone_model,
                                profile=profile_baseline(prof), profile_voiced_s=prof.voiced_s or 0.0, cfg=cfg)
    except Exception:
        log.exception("scoring attempt %s failed", attempt.id)
        result = failed_result(syllables, ["score_failed"])
    attempt.score_json = result.json
    for row in result.rows:
        db.add(SyllableScore(attempt_id=attempt.id, segment_id=segment.id, **row))
    if result.rows:
        add_frames(db, get_profile(db), result.voiced_f0)
