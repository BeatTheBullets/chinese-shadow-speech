from tests.helpers import make_tone_wav
from tests.test_lessons_api import _upload


def test_stats_shapes(client, tmp_path):
    lid = _upload(client, tmp_path)
    sid = client.get(f"/lessons/{lid}").json()["segments"][0]["id"]
    sess = client.post("/sessions", json={"lesson_id": lid, "mode": "echo"}).json()
    wav = make_tone_wav(tmp_path / "a.wav", 1.0)
    with open(wav, "rb") as f:
        client.post(f"/segments/{sid}/attempts", files={"audio": ("a.wav", f, "audio/wav")}, data={"session_id": sess["id"], "mode": "echo"})
    ls = client.get(f"/lessons/{lid}/stats").json()
    assert ls["segments"][0]["attempts"] == 1 and ls["segments"][0]["last"] is None
    act = client.get("/stats/activity", params={"days": 7}).json()
    assert len(act["days"]) == 7 and act["days"][-1]["attempts"] == 1 and act["days"][-1]["minutes"] > 0
    assert client.get("/stats/sentences").json() == {"regressed": [], "by_last": []}
    assert client.get("/stats/syllables").json() == {"syllables": []}
    assert client.get("/stats/tones").json() == {"tones": [], "pairs": []}


def test_lesson_stats_404(client):
    assert client.get("/lessons/9999/stats").status_code == 404
