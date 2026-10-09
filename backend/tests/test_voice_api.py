from sqlmodel import Session
from shadow.store.models import VoiceProfile


def test_voice_profile_get_and_reset(client):
    assert client.get("/voice-profile").json() == {"baseline_hz": None, "spread_st": None, "voiced_s": 0.0, "updated_at": None}
    with Session(client.app.state.engine) as db:
        db.add(VoiceProfile(frames_json=[118.0] * 10, baseline_hz=118.0, spread_st=9.5, voiced_s=250.0)); db.commit()
    got = client.get("/voice-profile").json()
    assert (got["baseline_hz"], got["spread_st"], got["voiced_s"]) == (118.0, 9.5, 250.0) and got["updated_at"]
    assert client.delete("/voice-profile").status_code == 204
    assert client.get("/voice-profile").json()["baseline_hz"] is None
