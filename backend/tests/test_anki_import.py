import base64
import numpy as np
import pytest
from sqlmodel import Session, select
from shadow.ingest import audio
from shadow.ingest.anki import AnkiNoteIn, clean_sentence, group_by_video, parse_source
from shadow.store.models import Lesson, Segment
from tests.helpers import make_tone_wav
from tests.conftest import wait_job


def test_parse_source_forms():
    assert parse_source("春天的茶.mp4 00:12:03.450") == ("春天的茶.mp4", 723.45)
    assert parse_source("春天的茶.mp4 12:03.450") == ("春天的茶.mp4", 723.45)
    assert parse_source("春天的茶_12345") == ("春天的茶", None)
    assert parse_source("春天的茶") == ("春天的茶", None)
    assert parse_source(None) == ("", None)


def test_parse_source_trailing_hms_timestamp():
    assert parse_source("春天的茶.mp4 (1h2m3s)") == ("春天的茶.mp4", 3723.0)
    assert parse_source("春天的茶.mp4 (2m3s)") == ("春天的茶.mp4", 123.0)
    assert parse_source("春天的茶.mp4 (45s)") == ("春天的茶.mp4", 45.0)
    assert parse_source("<div>春天的茶.mp4 (45s)</div>") == ("春天的茶.mp4", 45.0)


def test_clean_sentence_strips_html_sound_tags_and_traditional():
    assert clean_sentence("<div>你好，<b>世界</b>。[sound:a.mp3]</div>[sound:b.mp3]") == "你好，世界。"
    assert clean_sentence("學習中文") == "学习中文"


def _note(i, text, source="春天的茶.mp4 00:00:0%d.000" % 1, audio_b64="", translation=None):
    return AnkiNoteIn(note_id=i, text=text, translation=translation, source=source, url=None,
                      audio_b64=audio_b64, filename=f"{i}.wav")


def test_group_by_video():
    g = group_by_video([_note(1, "a", "v1.mp4 00:00:01.000"), _note(2, "b", "v2.mp4 00:00:01.000"), _note(3, "c", None)])
    assert set(g) == {"v1.mp4", "v2.mp4", ""}


def _b64(tmp_path, seconds=1.5):
    return base64.b64encode(make_tone_wav(tmp_path / "c.wav", seconds).read_bytes()).decode()


def _dict(i, text, source, b64, translation=None, filename=None):
    return {"note_id": i, "text": text, "translation": translation, "source": source, "url": None,
            "audio_b64": b64, "filename": filename or f"{i}.wav"}


def _segments(engine, lesson_id):
    with Session(engine) as db:
        return db.exec(select(Segment).where(Segment.lesson_id == lesson_id).order_by(Segment.idx)).all()


def test_import_creates_one_lesson_per_video_and_is_idempotent(client, tmp_path):
    b64 = _b64(tmp_path)
    notes = [
        _dict(1, "<div>你好，<b>世界</b>。</div>", "v1.mp4 00:00:01.000", b64, "Hello"),
        _dict(2, "再见。[sound:x.mp3]", "v1.mp4 00:00:05.000", b64),
        _dict(3, "欢迎回来。", "v2.mp4 00:00:02.000", b64),
    ]
    r = client.post("/lessons/anki", json={"query_name": "deck:Mining", "notes": notes})
    assert r.status_code == 202
    jobs = r.json()["jobs"]
    assert len(jobs) == 2
    for j in jobs:
        assert wait_job(client, j["job_id"])["status"] == "done"
    engine = client.app.state.engine
    with Session(engine) as db:
        lessons = db.exec(select(Lesson).where(Lesson.source_type == "anki")).all()
        assert sorted(l.title for l in lessons) == ["v1.mp4", "v2.mp4"]
        v1 = next(l for l in lessons if l.title == "v1.mp4")
        assert v1.status == "ready" and v1.transcript_json is None
        assert v1.duration_s == pytest.approx(3.5, abs=0.01)
    segs = _segments(engine, v1.id)
    assert [s.text for s in segs] == ["你好，世界。", "再见。"]
    assert segs[0].translation == "Hello" and segs[0].anki_note_id == 1
    assert segs[1].start_s > segs[0].end_s
    # each note's own clip is its segment: spans in the concatenated audio, 0.5 s apart, no transcript range
    assert (segs[0].start_s, segs[0].end_s) == (0.0, pytest.approx(1.5, abs=0.01))
    assert segs[1].start_s == pytest.approx(2.0, abs=0.01) and segs[1].end_s == pytest.approx(3.5, abs=0.01)
    assert all(s.char_from is None and s.char_to is None for s in segs)

    # re-import with one new note -> only one job, one new segment, appended after the existing audio
    r2 = client.post("/lessons/anki", json={"query_name": "deck:Mining", "notes": notes[:1] + [
        _dict(4, "新的句子。", "v1.mp4 00:00:09.000", b64)]})
    jobs2 = r2.json()["jobs"]
    assert len(jobs2) == 1
    assert wait_job(client, jobs2[0]["job_id"])["status"] == "done"
    segs = _segments(engine, v1.id)
    assert [s.anki_note_id for s in segs] == [1, 2, 4]
    assert [s.idx for s in segs] == [0, 1, 2]
    assert segs[2].start_s == pytest.approx(4.0, abs=0.01) and segs[2].end_s == pytest.approx(5.5, abs=0.01)
    assert audio.duration_s(client.app.state.deps.files.source_wav(v1.id)) == pytest.approx(5.5, abs=0.05)
    with Session(engine) as db:
        lesson = db.get(Lesson, v1.id)
        assert lesson.transcript_json is None and lesson.duration_s == pytest.approx(5.5, abs=0.01)
        assert db.get(Lesson, v1.id).status == "ready"
    # nothing new -> no jobs
    r3 = client.post("/lessons/anki", json={"query_name": "deck:Mining", "notes": notes[:2]})
    assert r3.json() == {"jobs": []}


def test_note_with_two_sound_tags_and_html_imports_plain_sentence(client, tmp_path):
    notes = [_dict(7, "<div><span style='x'>學習</span>中文[sound:a.mp3]<br>[sound:b.mp3]</div>", "v3.mp4 (45s)", _b64(tmp_path))]
    jobs = client.post("/lessons/anki", json={"query_name": "q", "notes": notes}).json()["jobs"]
    assert wait_job(client, jobs[0]["job_id"])["status"] == "done"
    segs = _segments(client.app.state.engine, jobs[0]["lesson_id"])
    assert [s.text for s in segs] == ["学习中文"]


def test_filename_cannot_escape_lesson_dir(client, tmp_path):
    notes = [_dict(8, "你好。", "v4.mp4", _b64(tmp_path), filename="../../../evil.wav")]
    jobs = client.post("/lessons/anki", json={"query_name": "q", "notes": notes}).json()["jobs"]
    assert wait_job(client, jobs[0]["job_id"])["status"] == "done"
    assert not (client.app.state.deps.files.data_dir / "evil.wav").exists()
    assert not (client.app.state.deps.files.lesson_dir(jobs[0]["lesson_id"]) / "anki_tmp").exists()


def test_bad_audio_marks_lesson_error(client):
    notes = [_dict(9, "你好。", "v5.mp4", base64.b64encode(b"not audio").decode())]
    jobs = client.post("/lessons/anki", json={"query_name": "q", "notes": notes}).json()["jobs"]
    assert wait_job(client, jobs[0]["job_id"])["status"] == "error"
    with Session(client.app.state.engine) as db:
        lesson = db.get(Lesson, jobs[0]["lesson_id"])
        assert lesson.status == "error" and "9" in lesson.error


def test_job_for_already_imported_notes_leaves_lesson_ready(client, tmp_path):
    from shadow.ingest.anki import ingest_anki_group
    notes = [_dict(1, "你好。", "v6.mp4", _b64(tmp_path))]
    job = client.post("/lessons/anki", json={"query_name": "q", "notes": notes}).json()["jobs"][0]
    assert wait_job(client, job["job_id"])["status"] == "done"
    ingest_anki_group(client.app.state.deps, client.app.state.engine, job["lesson_id"],
                      [AnkiNoteIn(**notes[0])], lambda s, f: None)
    with Session(client.app.state.engine) as db:
        assert db.get(Lesson, job["lesson_id"]).status == "ready"
    assert len(_segments(client.app.state.engine, job["lesson_id"])) == 1
