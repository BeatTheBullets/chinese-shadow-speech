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
    assert parse_source("春天的茶_12345") == ("春天的茶_12345", None)
    assert parse_source("春天的茶") == ("春天的茶", None)
    assert parse_source(None) == ("", None)


def test_parse_source_trailing_hms_timestamp():
    assert parse_source("春天的茶.mp4 (1h2m3s)") == ("春天的茶.mp4", 3723.0)
    assert parse_source("春天的茶.mp4 (2m3s)") == ("春天的茶.mp4", 123.0)
    assert parse_source("春天的茶.mp4 (45s)") == ("春天的茶.mp4", 45.0)
    assert parse_source("<div>春天的茶.mp4 (45s)</div>") == ("春天的茶.mp4", 45.0)


def test_parse_source_asbplayer_padded_timestamps():
    assert parse_source("episode.ass (00h00m08.3s)") == ("episode.ass", 8.3)
    assert parse_source("episode.ass") == ("episode.ass", None)
    assert parse_source("ep.srt (01h02m03.5s)") == ("ep.srt", 3723.5)
    assert parse_source("ep.srt (00h12m03.0s)") == ("ep.srt", 723.0)
    assert parse_source("ep.srt (2m03s)") == ("ep.srt", 123.0)
    assert parse_source("ep.srt (1h02m03s)") == ("ep.srt", 3723.0)
    assert parse_source("<div>ep.srt (00h00m08.3s)</div>") == ("ep.srt", 8.3)


def test_parse_source_keeps_numbered_names_distinct():
    assert parse_source("Lesson_1") == ("Lesson_1", None)
    assert parse_source("Lesson_2") == ("Lesson_2", None)


def test_group_by_video_orders_padded_timestamps_within_one_video():
    notes = [_note(1, "a", "ep01.srt (00h10m00.0s)"), _note(2, "b", "ep01.srt (00h02m05.5s)"),
             _note(3, "c", "ep01.srt (00h00m08.3s)")]
    g = group_by_video(notes)
    assert list(g) == ["ep01.srt"]
    assert [n.note_id for n in g["ep01.srt"]] == [3, 2, 1]


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


def test_hostile_filename_writes_nothing_outside_the_lesson_dir(client, tmp_path):
    files = client.app.state.deps.files
    notes = [_dict(8, "你好。", "v4.mp4", _b64(tmp_path), filename="../../../evil.wav")]
    jobs = client.post("/lessons/anki", json={"query_name": "q", "notes": notes}).json()["jobs"]
    assert wait_job(client, jobs[0]["job_id"])["status"] == "done"
    lesson_dir = files.lesson_dir(jobs[0]["lesson_id"])
    stray = [p for p in files.data_dir.parent.rglob("*") if p.is_file() and lesson_dir not in p.parents
             and p.name != "c.wav" and p.suffix not in (".db", ".sqlite")]      # c.wav: the test's own input
    assert stray == []
    assert not (lesson_dir / "anki_tmp").exists()


def _lesson(client, lesson_id):
    with Session(client.app.state.engine) as db:
        return db.get(Lesson, lesson_id)


def test_only_bad_audio_errors_the_lesson(client):
    notes = [_dict(9, "你好。", "v5.mp4", base64.b64encode(b"not audio").decode())]
    jobs = client.post("/lessons/anki", json={"query_name": "q", "notes": notes}).json()["jobs"]
    assert wait_job(client, jobs[0]["job_id"])["status"] == "error"
    lesson = _lesson(client, jobs[0]["lesson_id"])
    assert lesson.status == "error" and "no usable notes" in lesson.error


def test_bad_note_is_skipped_and_recorded_but_good_notes_import(client, tmp_path, caplog):
    b64 = _b64(tmp_path)
    notes = [_dict(1, "你好。", "v7.mp4 00:00:01.000", b64),
             _dict(2, "坏的。", "v7.mp4 00:00:02.000", ""),                                   # empty audio
             _dict(3, "也坏。", "v7.mp4 00:00:03.000", base64.b64encode(b"nope").decode()),   # undecodable
             _dict(4, "再见。", "v7.mp4 00:00:04.000", b64)]
    with caplog.at_level("WARNING"):
        jobs = client.post("/lessons/anki", json={"query_name": "q", "notes": notes}).json()["jobs"]
        assert wait_job(client, jobs[0]["job_id"])["status"] == "done"
    lid = jobs[0]["lesson_id"]
    assert [s.anki_note_id for s in _segments(client.app.state.engine, lid)] == [1, 4]
    lesson = _lesson(client, lid)
    assert lesson.status == "ready" and lesson.error is None
    assert set(lesson.meta_json["skipped_notes"]) == {"2", "3"}
    assert "skipping Anki note 2" in caplog.text
    # an identical import creates no job, even for the skipped notes
    assert client.post("/lessons/anki", json={"query_name": "q", "notes": notes}).json() == {"jobs": []}


def test_reimport_with_only_an_empty_text_note_keeps_lesson_ready(client, tmp_path):
    b64 = _b64(tmp_path)
    first = [_dict(1, "你好。", "v8.mp4", b64)]
    job = client.post("/lessons/anki", json={"query_name": "q", "notes": first}).json()["jobs"][0]
    assert wait_job(client, job["job_id"])["status"] == "done"
    again = first + [_dict(2, "<div></div>", "v8.mp4", b64)]
    assert client.post("/lessons/anki", json={"query_name": "q", "notes": again}).json() == {"jobs": []}
    assert _lesson(client, job["lesson_id"]).status == "ready"
    assert len(_segments(client.app.state.engine, job["lesson_id"])) == 1


def test_reimport_with_only_a_bad_audio_note_keeps_lesson_ready_and_does_not_repeat(client, tmp_path):
    b64 = _b64(tmp_path)
    first = [_dict(1, "你好。", "v9.mp4", b64)]
    job = client.post("/lessons/anki", json={"query_name": "q", "notes": first}).json()["jobs"][0]
    assert wait_job(client, job["job_id"])["status"] == "done"
    again = first + [_dict(2, "坏的。", "v9.mp4", "")]
    jobs = client.post("/lessons/anki", json={"query_name": "q", "notes": again}).json()["jobs"]
    assert len(jobs) == 1 and wait_job(client, jobs[0]["job_id"])["status"] == "done"
    lesson = _lesson(client, job["lesson_id"])
    assert lesson.status == "ready" and set(lesson.meta_json["skipped_notes"]) == {"2"}
    assert client.post("/lessons/anki", json={"query_name": "q", "notes": again}).json() == {"jobs": []}


def test_a_notes_translation_is_kept_and_a_note_without_one_has_none(client, tmp_path):
    b64 = _b64(tmp_path)
    notes = [_dict(1, "你好。", "v10.mp4 (1s)", b64, "Hello"), _dict(2, "再见。", "v10.mp4 (5s)", b64)]
    job = client.post("/lessons/anki", json={"query_name": "q", "notes": notes}).json()["jobs"][0]
    assert wait_job(client, job["job_id"])["status"] == "done"
    assert [s.translation for s in _segments(client.app.state.engine, job["lesson_id"])] == ["Hello", None]


def test_title_and_speaker_are_simplified_but_source_ref_keeps_the_raw_name(client, tmp_path):
    notes = [_dict(1, "你好。", "學習中文.mp4 (1s)", _b64(tmp_path))]
    job = client.post("/lessons/anki", json={"query_name": "q", "notes": notes}).json()["jobs"][0]
    assert job["title"] == "学习中文.mp4"
    lesson = _lesson(client, job["lesson_id"])
    assert (lesson.title, lesson.speaker, lesson.source_ref) == ("学习中文.mp4", "学习中文.mp4", "video::學習中文.mp4")


def test_job_for_already_imported_notes_leaves_lesson_ready(client, tmp_path):
    from shadow.ingest.anki import ingest_anki_group
    notes = [_dict(1, "你好。", "v6.mp4", _b64(tmp_path))]
    job = client.post("/lessons/anki", json={"query_name": "q", "notes": notes}).json()["jobs"][0]
    assert wait_job(client, job["job_id"])["status"] == "done"
    ingest_anki_group(client.app.state.deps, client.app.state.engine, job["lesson_id"],
                      [AnkiNoteIn(**notes[0])], lambda s, f: None)
    assert _lesson(client, job["lesson_id"]).status == "ready"
    assert len(_segments(client.app.state.engine, job["lesson_id"])) == 1


def _anki_lessons(client):
    with Session(client.app.state.engine) as db:
        return db.exec(select(Lesson).where(Lesson.source_type == "anki")).all()


def test_two_queries_sharing_a_video_feed_one_lesson_without_duplicates(client, tmp_path):
    """Spec §7.4/§8.1: one lesson per source video, whichever query (e.g. the whole deck and rated:1) found it."""
    b64 = _b64(tmp_path)
    deck = [_dict(1, "你好。", "v11.mp4 00:00:01.000", b64), _dict(2, "再见。", "v11.mp4 00:00:05.000", b64)]
    today = [_dict(2, "再见。", "v11.mp4 00:00:05.000", b64), _dict(3, "欢迎回来。", "v11.mp4 00:00:09.000", b64)]
    first = client.post("/lessons/anki", json={"query_name": "deck:Mining tag:asbplayer", "notes": deck}).json()["jobs"]
    assert wait_job(client, first[0]["job_id"])["status"] == "done"
    second = client.post("/lessons/anki", json={"query_name": "rated:1", "notes": today}).json()["jobs"]
    assert [j["lesson_id"] for j in second] == [first[0]["lesson_id"]]
    assert wait_job(client, second[0]["job_id"])["status"] == "done"
    lessons = _anki_lessons(client)
    assert [(l.title, l.source_ref) for l in lessons] == [("v11.mp4", "video::v11.mp4")]
    assert [s.anki_note_id for s in _segments(client.app.state.engine, lessons[0].id)] == [1, 2, 3]
    # renaming or re-running either query finds the same lesson and adds nothing
    assert client.post("/lessons/anki", json={"query_name": "renamed", "notes": deck + today}).json() == {"jobs": []}


def test_overlapping_imports_from_two_queries_do_not_duplicate_notes(client, tmp_path):
    b64 = _b64(tmp_path)
    deck = [_dict(1, "你好。", "v12.mp4 (1s)", b64), _dict(2, "再见。", "v12.mp4 (5s)", b64)]
    today = [_dict(2, "再见。", "v12.mp4 (5s)", b64)]
    a = client.post("/lessons/anki", json={"query_name": "deck", "notes": deck}).json()["jobs"]
    b = client.post("/lessons/anki", json={"query_name": "rated:1", "notes": today}).json()["jobs"]   # before a ran
    for j in a + b:
        assert wait_job(client, j["job_id"])["status"] == "done"
    lessons = _anki_lessons(client)
    assert len(lessons) == 1 and lessons[0].status == "ready"
    assert [s.anki_note_id for s in _segments(client.app.state.engine, lessons[0].id)] == [1, 2]


def test_notes_without_a_source_go_to_a_lesson_per_query(client, tmp_path):
    b64 = _b64(tmp_path)
    for q, nid in (("deck", 1), ("rated:1", 2)):
        job = client.post("/lessons/anki", json={"query_name": q, "notes": [_dict(nid, "你好。", None, b64)]}).json()["jobs"][0]
        assert wait_job(client, job["job_id"])["status"] == "done"
    assert sorted((l.title, l.source_ref) for l in _anki_lessons(client)) == [("deck", "query::deck"), ("rated:1", "query::rated:1")]
