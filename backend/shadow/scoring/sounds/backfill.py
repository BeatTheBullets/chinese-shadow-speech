"""Back-fill sound results onto takes scored before Phase 3a (spec §back-fill). Only sound fields are written: the tone
result and `overall` of a stored take never change."""
from __future__ import annotations
import copy
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from sqlalchemy.orm.attributes import flag_modified
from sqlmodel import Session, select
from shadow.ingest import audio
from shadow.scoring.pitch import trim_silence
from shadow.scoring.reference import reference_audio, segment_syllables, sound_ref_key
from shadow.scoring.score import check_sounds
from shadow.scoring.windows import windows
from shadow.store.models import Attempt, Segment, SyllableScore

if TYPE_CHECKING:
    from shadow.deps import Deps

log = logging.getLogger(__name__)


def backfill_attempt(deps: Deps, db: Session, attempt: Attempt) -> bool:
    """True when the take got sound results. False (nothing changed) when it was never scored, the detector is off,
    its audio or reference is gone, the alignment no longer matches the syllables, or the sound check failed."""
    sj = attempt.score_json
    if not sj or sj.get("overall") is None or deps.sounds is None:
        return False
    if not attempt.audio_path or not Path(attempt.audio_path).exists():
        return False
    seg = db.get(Segment, attempt.segment_id)
    if seg is None or not seg.clip_wav_path or not Path(seg.clip_wav_path).exists():
        return False
    syllables = segment_syllables(seg)
    stored = sj.get("syllables") or []
    if len(stored) != len(syllables):
        return False
    wav, sr = audio.read_wav(Path(attempt.audio_path))
    trimmed, _ = trim_silence(wav, sr)
    spans = deps.aligner.align(trimmed, sr, seg.text)
    if len(spans) != len(syllables):
        return False
    usr_win = windows([(s.start, s.end) for s in spans], len(trimmed) / sr)
    ref_wav, ref_sr = reference_audio(seg)
    got = check_sounds(deps.sounds, take=trimmed, sr=sr, usr_win=usr_win, ref_wav=ref_wav, ref_sr=ref_sr,
                       ref_key=sound_ref_key(seg, syllables), syllables=syllables, statuses=[s["status"] for s in stored])
    if got is None:
        return False
    checked, off, applied = got
    new = copy.deepcopy(sj)               # a fresh object, so the JSON column registers the change
    new["sounds_checked"], new["sounds_off"] = checked, off
    for js, (f, _) in zip(new["syllables"], applied):
        js["sound"] = f
    attempt.score_json = new
    flag_modified(attempt, "score_json")
    rows = {r.idx: r for r in db.exec(select(SyllableScore).where(SyllableScore.attempt_id == attempt.id))}
    for i, (_, t) in enumerate(applied):
        if i in rows:
            rows[i].sound_status, rows[i].heard_syllable, rows[i].seg_score = t
            db.add(rows[i])
    db.add(attempt)
    return True
