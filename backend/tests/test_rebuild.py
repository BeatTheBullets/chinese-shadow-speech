from sqlmodel import Session, select
from shadow.ingest.text import Cue
from shadow.ingest.transcript import Transcript, transcript_from_cues
from shadow.store.models import Attempt, Lesson, Segment, SyllableScore, VoiceProfile
from tests.conftest import LESSON_TEXT, wait_job
from tests.helpers import make_tone_wav
from tests.test_lessons_api import _upload
from tests.test_pipeline import _NoAligner, _setup, _srt

# The old lesson: 0-3 s 我今天想跟你们聊一聊学中文的方法。| 3-5 s 其实方法有很多。| 5-7.5 s 但是最重要的是坚持。
# The re-transcription splits the first sentence unevenly: most of its time goes to the second new sentence.
NEW_TEXT = [
    (0.0, 1.0, "我今天想。"),
    (1.0, 3.0, "跟你们聊一聊学中文的方法。"),
    (3.0, 5.0, "其实方法有很多。"),
    (5.0, 7.5, "但是最重要的是坚持。"),
]


def test_match_segment_by_largest_overlap_then_nearest_midpoint():
    from shadow.ingest.rebuild import match_segment
    new = [(10, 0.0, 1.0), (11, 1.0, 3.0), (12, 3.0, 5.0), (13, 9.0, 10.0)]
    assert match_segment(0.0, 3.0, new) == 11                 # overlaps 10 by 1 s, 11 by 2 s
    assert match_segment(0.5, 1.5, new) == 10                 # 0.5 s each: the earlier
    assert match_segment(6.0, 6.5, new) == 12                 # no overlap: nearest midpoint (4 vs 9.5)
    assert match_segment(6.5, 7.0, new) == 12                 # equally near (2.75 s each): the earlier


def _post_take(client, tmp_path, sid, name):
    with open(make_tone_wav(tmp_path / f"{name}.wav", 2.6), "rb") as f:
        r = client.post(f"/segments/{sid}/attempts", files={"audio": ("a.wav", f, "audio/wav")}, data={"mode": "echo"})
    assert r.status_code == 201
    return r.json()["id"]


def _syllables(seg) -> int:
    return len([s for w in seg["words_json"] for s in w["syllables"]])


def test_rebuild_replaces_sentences_and_moves_takes_flags_and_notes_by_time(client, tmp_path):
    lid = _upload(client, tmp_path)
    old = client.get(f"/lessons/{lid}").json()["segments"]
    a1 = _post_take(client, tmp_path, old[0]["id"], "a1")
    a2 = _post_take(client, tmp_path, old[0]["id"], "a2")
    a3 = _post_take(client, tmp_path, old[2]["id"], "a3")
    client.patch(f"/segments/{old[0]['id']}", json={"difficulty_flag": True})
    client.patch(f"/segments/{old[1]['id']}", json={"anki_note_id": 77})
    engine, files = client.app.state.engine, client.app.state.files
    with Session(engine) as db:
        voiced_before = db.exec(select(VoiceProfile)).one().voiced_s
    client.app.state.deps.asr._tr = transcript_from_cues([Cue(a, b, t) for a, b, t in NEW_TEXT])

    r = client.post(f"/lessons/{lid}/rebuild")
    assert r.status_code == 202
    assert wait_job(client, r.json()["job_id"])["status"] == "done"

    detail = client.get(f"/lessons/{lid}").json()
    segs = detail["segments"]
    assert detail["status"] == "ready" and [s["text"] for s in segs] == [t for _, _, t in NEW_TEXT]
    assert not {s["id"] for s in segs} & {s["id"] for s in old}
    by_text = {s["text"]: s for s in segs}
    first, notes, last = by_text[NEW_TEXT[1][2]], by_text[NEW_TEXT[2][2]], by_text[NEW_TEXT[3][2]]
    assert first["difficulty_flag"] and not by_text[NEW_TEXT[0][2]]["difficulty_flag"]
    assert notes["anki_note_id"] == 77
    assert (first["attempts"], last["attempts"], by_text[NEW_TEXT[0][2]]["attempts"]) == (2, 1, 0)
    with Session(engine) as db:
        atts = {a.id: a for a in db.exec(select(Attempt)).all()}
        assert set(atts) == {a1, a2, a3}                         # nothing deleted
        assert [atts[a].segment_id for a in (a1, a2, a3)] == [first["id"], first["id"], last["id"]]
        for aid, seg in ((a1, first), (a2, first), (a3, last)):  # re-scored against the new sentence
            assert len(atts[aid].score_json["syllables"]) == _syllables(seg)
            rows = db.exec(select(SyllableScore).where(SyllableScore.attempt_id == aid)).all()
            assert len(rows) == _syllables(seg) and {x.segment_id for x in rows} == {seg["id"]}
        assert db.exec(select(VoiceProfile)).one().voiced_s == voiced_before   # takes not counted twice
        assert db.get(Lesson, lid).transcript_json["chars"][4]["c"] == "。"
    clips = files.lesson_dir(lid) / "clips"
    assert sorted(p.name for p in clips.glob("*.wav")) == [f"{i}.wav" for i in range(4)]
    with Session(engine) as db:
        rows = db.exec(select(Segment).where(Segment.lesson_id == lid).order_by(Segment.idx)).all()
        assert [(s.idx, s.clip_wav_path) for s in rows] == [(i, str(files.clip_wav(lid, i))) for i in range(4)]
    assert len(detail["passages"]) >= 1


def test_rebuild_recomputes_the_lesson_pitch_baseline(client, tmp_path):
    lid = _upload(client, tmp_path)
    with Session(client.app.state.engine) as db:
        lesson = db.get(Lesson, lid)
        lesson.meta_json = {**(lesson.meta_json or {}), "pitch": {"baseline_hz": 1.0, "spread_st": 1.0, "frames": 1}}
        db.add(lesson); db.commit()
    r = client.post(f"/lessons/{lid}/rebuild")
    assert wait_job(client, r.json()["job_id"])["status"] == "done"
    with Session(client.app.state.engine) as db:
        assert "pitch" not in (db.get(Lesson, lid).meta_json or {})


def test_rebuild_refuses_a_lesson_being_processed_an_anki_lesson_and_an_unknown_one(client, tmp_path):
    lid = _upload(client, tmp_path)
    with Session(client.app.state.engine) as db:
        lesson = db.get(Lesson, lid); lesson.status = "processing"; db.add(lesson)
        anki = Lesson(title="a", source_type="anki", status="ready"); db.add(anki); db.commit(); db.refresh(anki)
        anki_id = anki.id
    assert client.post(f"/lessons/{lid}/rebuild").status_code == 409
    assert client.post(f"/lessons/{anki_id}/rebuild").status_code == 400
    assert client.post("/lessons/999/rebuild").status_code == 404


def test_a_second_rebuild_request_is_refused_until_the_first_is_done(client, tmp_path):
    lid = _upload(client, tmp_path)
    first = client.post(f"/lessons/{lid}/rebuild")
    assert first.status_code == 202
    assert client.post(f"/lessons/{lid}/rebuild").status_code == 409     # the lesson is processing at once
    assert wait_job(client, first.json()["job_id"])["status"] == "done"


def test_a_failed_rebuild_leaves_the_lesson_as_it_was(client, tmp_path):
    lid = _upload(client, tmp_path)
    old = client.get(f"/lessons/{lid}").json()["segments"]
    aid = _post_take(client, tmp_path, old[0]["id"], "a")
    client.app.state.deps.asr._tr = Transcript()                 # no speech
    r = client.post(f"/lessons/{lid}/rebuild")
    job = wait_job(client, r.json()["job_id"])
    assert job["status"] == "error" and "no speech" in job["error"]
    detail = client.get(f"/lessons/{lid}").json()
    keys = ("id", "idx", "text", "start_s", "end_s")
    assert detail["status"] == "ready"
    assert [[s[k] for k in keys] for s in detail["segments"]] == [[s[k] for k in keys] for s in old]
    with Session(client.app.state.engine) as db:
        assert db.get(Attempt, aid).segment_id == old[0]["id"]
    clips = client.app.state.files.lesson_dir(lid) / "clips"
    assert sorted(p.name for p in clips.glob("*.wav")) == [f"{i}.wav" for i in range(3)]


def test_rebuild_keeps_a_subtitle_lessons_text_and_retimes_it(data_dir, tmp_path):
    from shadow.ingest.pipeline import ingest_upload
    from shadow.ingest.rebuild import rebuild_lesson
    deps, engine, lid = _setup(data_dir, transcript_from_cues([Cue(a, b, t) for a, b, t in LESSON_TEXT]))
    deps.aligner = _NoAligner()
    ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 8.0), ("a.srt", _srt(LESSON_TEXT)),
                  lambda s, f: None)
    # the new recognition mishears 学 as 雪 and hears everything 0.5 s later
    deps.asr._tr = transcript_from_cues([Cue(a + 0.5, b + 0.5, t.replace("学", "雪")) for a, b, t in LESSON_TEXT])
    stages = []
    rebuild_lesson(deps, engine, lid, lambda s, f: stages.append(s))
    with Session(engine) as db:
        lesson = db.get(Lesson, lid)
        segs = db.exec(select(Segment).where(Segment.lesson_id == lid).order_by(Segment.idx)).all()
        assert [s.text for s in segs] == [t for _, _, t in LESSON_TEXT]            # the subtitles' 学
        assert segs[0].start_s == 0.38                                            # 0.5 s, padded
        assert lesson.meta_json["subtitle_match"] == 0.97 and lesson.status == "ready"
    assert deps.llm.rectify_locked == [True, True]
    assert [s for s in dict.fromkeys(stages)] == ["transcribe", "rectify", "align", "enrich", "clips", "rescore", "done"]


def test_a_rebuild_failing_after_its_new_sentences_are_cut_discards_them(client, tmp_path, monkeypatch):
    import shadow.ingest.rebuild as rebuild
    lid = _upload(client, tmp_path)
    old = client.get(f"/lessons/{lid}").json()["segments"]
    client.app.state.deps.asr._tr = transcript_from_cues([Cue(a, b, t) for a, b, t in NEW_TEXT])

    def swap(*a, **k):
        raise RuntimeError("disk full")
    monkeypatch.setattr(rebuild, "_swap", swap)
    job = wait_job(client, client.post(f"/lessons/{lid}/rebuild").json()["job_id"])
    assert job["status"] == "error" and job["error"] == "disk full"
    detail = client.get(f"/lessons/{lid}").json()
    assert detail["status"] == "ready" and [s["id"] for s in detail["segments"]] == [s["id"] for s in old]
    clips = client.app.state.files.lesson_dir(lid) / "clips"
    assert sorted(p.name for p in clips.iterdir()) == sorted(f"{i}.{x}" for i in range(3) for x in ("wav", "opus"))
