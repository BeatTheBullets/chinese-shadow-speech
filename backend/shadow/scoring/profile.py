"""The learner's voice profile (Phase 2 spec §2): one row, the most recent voiced frames and their baseline."""
from __future__ import annotations
import numpy as np
from sqlmodel import Session, delete, select
from shadow.scoring.pitch import STEP_S, Baseline, baseline_of
from shadow.store.models import VoiceProfile, now

MAX_FRAMES = 6000                        # ≈ 60 s of voiced speech


def get_profile(db: Session) -> VoiceProfile:
    p = db.exec(select(VoiceProfile).order_by(VoiceProfile.id)).first()
    return p if p is not None else VoiceProfile()


def profile_baseline(p: VoiceProfile) -> Baseline | None:
    return Baseline(p.baseline_hz, p.spread_st) if p.baseline_hz and p.spread_st else None


def add_frames(db: Session, p: VoiceProfile, f0_voiced: np.ndarray) -> None:
    frames = (list(p.frames_json or []) + [round(float(x), 1) for x in f0_voiced])[-MAX_FRAMES:]
    b = baseline_of(np.asarray(frames))
    p.frames_json = frames
    p.baseline_hz, p.spread_st = (b.hz, b.spread_st) if b else (None, None)
    p.voiced_s = (p.voiced_s or 0.0) + len(f0_voiced) * STEP_S
    p.updated_at = now()
    db.add(p)


def reset_profile(db: Session) -> None:
    db.exec(delete(VoiceProfile))
