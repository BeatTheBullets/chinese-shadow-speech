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


def plan_backfill(deps: Deps, db: Session, attempt: Attempt) -> tuple[dict, list[tuple]] | None:
    """The compute step: may raise, never writes. Returns (new score_json, per-syllable (sound_status, heard_syllable,
    seg_score)), or None (nothing to do) when the take was never scored, the detector is off, its audio or reference
    is gone, the alignment no longer matches the syllables, or the sound check failed."""
    sj = attempt.score_json
    if not sj or sj.get("overall") is None or deps.sounds is None:
        return None
    if not attempt.audio_path or not Path(attempt.audio_path).exists():
        return None
    seg = db.get(Segment, attempt.segment_id)
    if seg is None or not seg.clip_wav_path or not Path(seg.clip_wav_path).exists():
        return None
    syllables = segment_syllables(seg)
    stored = sj.get("syllables") or []
    if len(stored) != len(syllables):
        return None
    wav, sr = audio.read_wav(Path(attempt.audio_path))
    trimmed, _ = trim_silence(wav, sr)
    spans = deps.aligner.align(trimmed, sr, seg.text)
    if len(spans) != len(syllables):
        return None
    usr_win = windows([(s.start, s.end) for s in spans], len(trimmed) / sr)
    ref_wav, ref_sr = reference_audio(seg)
    got = check_sounds(deps.sounds, take=trimmed, sr=sr, usr_win=usr_win, ref_wav=ref_wav, ref_sr=ref_sr,
                       ref_key=sound_ref_key(seg, syllables), syllables=syllables, statuses=[s["status"] for s in stored])
    if got is None:
        return None
    checked, off, applied = got
    new = copy.deepcopy(sj)               # a fresh object, so the JSON column registers the change
    new["sounds_checked"], new["sounds_off"] = checked, off
    for js, (f, _) in zip(new["syllables"], applied):
        js["sound"] = f
    return new, [t for _, t in applied]


def apply_backfill(db: Session, attempt: Attempt, plan: tuple[dict, list[tuple]]) -> None:
    """The apply step: only assigns values computed by `plan_backfill`."""
    new, row_values = plan
    attempt.score_json = new
    flag_modified(attempt, "score_json")
    rows = {r.idx: r for r in db.exec(select(SyllableScore).where(SyllableScore.attempt_id == attempt.id))}
    for i, t in enumerate(row_values):
        if i in rows:
            rows[i].sound_status, rows[i].heard_syllable, rows[i].seg_score = t
            db.add(rows[i])
    db.add(attempt)


def backfill_attempt(deps: Deps, db: Session, attempt: Attempt) -> bool:
    """True when the take got sound results (applied to the session, uncommitted); False, nothing changed, otherwise."""
    plan = plan_backfill(deps, db, attempt)
    if plan is None:
        return False
    apply_backfill(db, attempt, plan)
    return True


def backfill_all(deps: Deps, db: Session, *, dry_run: bool = False, every: int = 20, after_commit=lambda: None) -> dict:
    """All takes oldest first. A raise while computing one take (corrupt wav, aligner error, a stored syllable without
    a status) is logged and counted as failed, and the run goes on; nothing was written for it. A dry run never
    applies, so the session stays clean. Commits every `every` takes."""
    out = {"done": 0, "skipped": 0, "failed": 0, "slips": 0}
    for n, att in enumerate(db.exec(select(Attempt).order_by(Attempt.created_at, Attempt.id)).all(), 1):
        try:
            plan = plan_backfill(deps, db, att)
        except Exception:  # noqa: BLE001
            log.exception("back-fill of attempt %s failed; it is left as it was", att.id)
            out["failed"] += 1
            continue
        if plan is None:
            out["skipped"] += 1
        else:
            out["done"] += 1
            out["slips"] += plan[0].get("sounds_off") or 0
            if not dry_run:
                apply_backfill(db, att, plan)
        if not dry_run and n % every == 0:
            db.commit()
            after_commit()
    if not dry_run:
        db.commit()
    return out
