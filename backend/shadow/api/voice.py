"""The learner's voice profile (Phase 2 spec §2, §6): shown in Settings, resettable."""
from fastapi import APIRouter, Depends, Response
from sqlmodel import Session, select
from shadow.scoring.profile import reset_profile
from shadow.store.db import get_session
from shadow.store.models import VoiceProfile

router = APIRouter()


@router.get("/voice-profile")
def get_voice_profile(db: Session = Depends(get_session)):
    p = db.exec(select(VoiceProfile).order_by(VoiceProfile.id)).first()
    if p is None:
        return {"baseline_hz": None, "spread_st": None, "voiced_s": 0.0, "updated_at": None}
    return {"baseline_hz": p.baseline_hz, "spread_st": p.spread_st, "voiced_s": p.voiced_s, "updated_at": p.updated_at}


@router.delete("/voice-profile", status_code=204)
def delete_voice_profile(db: Session = Depends(get_session)):
    reset_profile(db)
    db.commit()
    return Response(status_code=204)
