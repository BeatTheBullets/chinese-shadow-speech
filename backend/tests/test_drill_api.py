from sqlmodel import Session
from shadow.store.models import Attempt, DrillSession
from tests.helpers import make_tone_wav
from tests.test_lessons_api import _upload


def _post(client, path, sid, **data):
    with open(path, "rb") as f:
        return client.post(f"/segments/{sid}/attempts", files={"audio": ("a.wav", f, "audio/wav")}, data=data)


def test_a_drill_take_is_an_attempt_linked_to_its_drill_session(client, tmp_path):
    lid = _upload(client, tmp_path)
    sid = client.get(f"/lessons/{lid}").json()["segments"][0]["id"]
    with Session(client.app.state.engine) as db:
        ds = DrillSession(kind="tone", key="3", label="tone 3 (low)", items_json=[]); db.add(ds); db.commit(); db.refresh(ds)
    r = _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), sid, mode="drill", drill_session_id=str(ds.id))
    assert r.status_code == 201
    with Session(client.app.state.engine) as db:
        assert db.get(Attempt, r.json()["id"]).drill_session_id == ds.id
    assert _post(client, make_tone_wav(tmp_path / "u.wav", 2.6), sid, mode="drill", drill_session_id="9999").status_code == 404


def test_create_sound_drill(client):
    from sqlmodel import Session
    from shadow.store.models import Lesson, Segment
    with Session(client.app.state.engine) as db:
        les = Lesson(title="L", source_type="upload", status="ready"); db.add(les); db.commit(); db.refresh(les)
        db.add(Segment(lesson_id=les.id, idx=0, start_s=0, end_s=1, text="吃吃吃吃", clip_wav_path="c.wav",
                       words_json=[{"word": "吃吃吃吃", "pinyin": "", "tones": [1] * 4, "char_from": 0, "char_to": 4,
                                    "syllables": [{"ch": "吃", "pinyin": "chi", "pinyin_toneless": "chi", "tone": 1}] * 4}]))
        db.commit()
    r = client.post("/drill/sessions", json={"kind": "sound", "key": "ch>c"})
    assert r.status_code == 201 and r.json()["label"] == "ch (not c)"
    assert client.post("/drill/sessions", json={"kind": "sound", "key": "x>y"}).status_code == 400
