import soundfile as sf
from sqlmodel import Session, select
from shadow.ingest import audio
from shadow.store.models import Segment
from tests.test_anki_import import _b64, _dict
from tests.test_lessons_api import _upload
from tests.conftest import wait_job


def _segments(client, lid):
    return client.get(f"/lessons/{lid}").json()["segments"]


def _assert_clips_consistent(client, lid, mp3=False):
    """Every segment's clip files sit at its own idx and hold its own audio (duration = its bounds)."""
    files = client.app.state.files
    with Session(client.app.state.engine) as db:
        rows = db.exec(select(Segment).where(Segment.lesson_id == lid).order_by(Segment.idx)).all()
    stems = {p.stem for p in files.lesson_dir(lid).joinpath("clips").iterdir()}
    assert stems == {str(i) for i in range(len(rows))}            # no clip files left at a vacated idx
    for s in rows:
        assert s.clip_wav_path == str(files.clip_wav(lid, s.idx))
        assert s.clip_opus_path == str(files.clip_opus(lid, s.idx))
        assert files.clip_opus(lid, s.idx).exists()
        assert abs(sf.info(s.clip_wav_path).duration - (s.end_s - s.start_s)) < 0.02, s.idx
        if mp3:
            r = client.get(f"/segments/{s.id}/audio", params={"fmt": "mp3"})
            assert r.status_code == 200
            assert abs(audio.duration_s(files.clip_mp3(lid, s.idx)) - (s.end_s - s.start_s)) < 0.15, s.idx  # + encoder padding


def _render_all_mp3(client, lid):
    for s in _segments(client, lid):
        assert client.get(f"/segments/{s['id']}/audio", params={"fmt": "mp3"}).status_code == 200


def test_audio_formats(client, tmp_path):
    lid = _upload(client, tmp_path)
    sid = _segments(client, lid)[0]["id"]
    for fmt, ctype in (("wav", "audio/wav"), ("opus", "audio/ogg"), ("mp3", "audio/mpeg")):
        r = client.get(f"/segments/{sid}/audio", params={"fmt": fmt})
        assert r.status_code == 200 and r.headers["content-type"].startswith(ctype), fmt
    assert client.get(f"/segments/{sid}/audio", params={"fmt": "flac"}).status_code == 400
    assert client.get("/segments/999/audio").status_code == 404


def test_audio_is_revalidated_on_every_use(client, tmp_path):
    """An edit re-cuts the clip under the same URL, so the browser must revalidate (ETag -> cheap 304)."""
    lid = _upload(client, tmp_path)
    sid = _segments(client, lid)[0]["id"]
    for fmt in ("wav", "opus", "mp3"):
        r = client.get(f"/segments/{sid}/audio", params={"fmt": fmt})
        assert r.headers["cache-control"] == "no-cache", fmt
        assert r.headers.get("etag") and r.headers.get("last-modified"), fmt
        again = client.get(f"/segments/{sid}/audio", params={"fmt": fmt}, headers={"If-None-Match": r.headers["etag"]})
        assert again.status_code == 304, fmt


def test_patch_flag_and_text(client, tmp_path):
    lid = _upload(client, tmp_path)
    seg = _segments(client, lid)[1]
    assert client.patch(f"/segments/{seg['id']}", json={"difficulty_flag": True}).json()["difficulty_flag"] is True
    before = client.app.state.files.clip_wav(lid, 1).stat().st_mtime_ns
    same = client.patch(f"/segments/{seg['id']}", json={"text": seg["text"]}).json()
    assert client.app.state.files.clip_wav(lid, 1).stat().st_mtime_ns == before      # no-op
    assert same["ref_alignment_json"] == seg["ref_alignment_json"] and same["difficulty_flag"] is True
    changed = client.patch(f"/segments/{seg['id']}", json={"text": "其实办法有很多。"}).json()
    assert changed["text"] == "其实办法有很多。" and changed["words_json"][1]["word"] == "办法"
    assert len(changed["ref_alignment_json"]) == 7
    assert changed["translation"] == "en:其实办法有很多。"
    assert client.app.state.files.clip_wav(lid, 1).stat().st_mtime_ns != before
    _assert_clips_consistent(client, lid)


def test_patch_text_is_simplified_and_traditional_spelling_of_same_text_is_noop(client, tmp_path):
    lid = _upload(client, tmp_path)
    seg = _segments(client, lid)[1]
    before = client.app.state.files.clip_wav(lid, 1).stat().st_mtime_ns
    client.patch(f"/segments/{seg['id']}", json={"text": "其實方法有很多。"})        # traditional of current text
    assert client.app.state.files.clip_wav(lid, 1).stat().st_mtime_ns == before
    out = client.patch(f"/segments/{seg['id']}", json={"text": "其實辦法有很多。"}).json()
    assert out["text"] == "其实办法有很多。"


def test_patch_text_rejects_text_without_speech(client, tmp_path):
    lid = _upload(client, tmp_path)
    seg = _segments(client, lid)[1]
    assert client.patch(f"/segments/{seg['id']}", json={"text": "。。"}).status_code == 400
    assert _segments(client, lid)[1]["text"] == seg["text"]
    assert client.patch("/segments/999", json={"difficulty_flag": True}).status_code == 404


def test_patch_text_survives_translation_failure(client, tmp_path, monkeypatch):
    lid = _upload(client, tmp_path)
    seg = _segments(client, lid)[1]

    def boom(xs):
        raise RuntimeError("llm down")
    monkeypatch.setattr(client.app.state.deps.llm, "translate", boom)
    out = client.patch(f"/segments/{seg['id']}", json={"text": "其实办法有很多。"})
    assert out.status_code == 200 and out.json()["translation"] is None


def test_patch_records_the_exported_anki_note_without_reenrich(client, tmp_path):
    lid = _upload(client, tmp_path)
    seg = _segments(client, lid)[1]
    before = client.app.state.files.clip_wav(lid, 1).stat().st_mtime_ns
    out = client.patch(f"/segments/{seg['id']}", json={"anki_note_id": 1700000000123}).json()
    assert out["anki_note_id"] == 1700000000123
    assert (out["text"], out["words_json"], out["ref_alignment_json"], out["translation"]) == \
        (seg["text"], seg["words_json"], seg["ref_alignment_json"], seg["translation"])
    assert client.app.state.files.clip_wav(lid, 1).stat().st_mtime_ns == before          # no re-enrich
    assert _segments(client, lid)[1]["anki_note_id"] == 1700000000123


def _row(client, sid):
    with Session(client.app.state.engine) as db:
        return db.get(Segment, sid)


def test_failed_reenrich_keeps_the_old_text_with_its_words_alignment_and_clip(client, tmp_path, monkeypatch):
    """A text edit is all or nothing: if re-enrich fails the segment keeps its old text, words, alignment and
    clip, and a retry of the same text tries again instead of being a no-op."""
    import shadow.ingest.reenrich as reenrich
    lid = _upload(client, tmp_path)
    seg = _segments(client, lid)[1]
    clip = client.app.state.files.clip_wav(lid, 1)
    before_row, before_clip = _row(client, seg["id"]), clip.read_bytes()

    def bad_pinyin(text):
        raise ValueError("no pinyin for 𠀀")
    monkeypatch.setattr(reenrich, "words_for", bad_pinyin)
    r = client.patch(f"/segments/{seg['id']}", json={"text": "其实办法有很多。", "difficulty_flag": True})
    assert r.status_code == 500
    assert "not changed" in r.json()["detail"] and "no pinyin" in r.json()["detail"]
    after = _row(client, seg["id"])
    assert (after.text, after.words_json, after.ref_alignment_json, after.difficulty_flag) == \
        (before_row.text, before_row.words_json, before_row.ref_alignment_json, False)
    assert clip.read_bytes() == before_clip

    monkeypatch.undo()                                  # the same edit, retried, now goes through
    ok = client.patch(f"/segments/{seg['id']}", json={"text": "其实办法有很多。"}).json()
    assert ok["text"] == "其实办法有很多。" and ok["words_json"][1]["word"] == "办法"
    _assert_clips_consistent(client, lid)


def test_failed_clip_encode_leaves_text_and_clip_files_untouched(client, tmp_path, monkeypatch):
    import subprocess
    lid = _upload(client, tmp_path)
    seg = _segments(client, lid)[1]
    files = client.app.state.files
    before_row = _row(client, seg["id"])
    before = (files.clip_wav(lid, 1).read_bytes(), files.clip_opus(lid, 1).read_bytes())

    def opus_fails(src, dst):                            # cut already wrote the new wav when this fails
        raise subprocess.CalledProcessError(1, ["ffmpeg"])
    monkeypatch.setattr(audio, "encode_opus", opus_fails)
    r = client.patch(f"/segments/{seg['id']}", json={"text": "其实办法有很多。"})
    assert r.status_code == 500 and "not changed" in r.json()["detail"] and "ffmpeg" in r.json()["detail"]
    after = _row(client, seg["id"])
    assert (after.text, after.start_s, after.end_s, after.words_json) == \
        (before_row.text, before_row.start_s, before_row.end_s, before_row.words_json)
    assert (files.clip_wav(lid, 1).read_bytes(), files.clip_opus(lid, 1).read_bytes()) == before
    assert sorted(p.name for p in files.lesson_dir(lid).joinpath("clips").iterdir()) == \
        ["0.opus", "0.wav", "1.opus", "1.wav", "2.opus", "2.wav"]           # no temporary leftovers


def test_resplit_and_merge(client, tmp_path):
    lid = _upload(client, tmp_path)
    _render_all_mp3(client, lid)            # stale mp3s must not survive the renumbering
    segs = _segments(client, lid)
    r = client.post(f"/segments/{segs[0]['id']}/resplit", json={"at_char_index": 7})
    assert r.status_code == 200
    assert [s["text"] for s in r.json()] == ["我今天想跟你们", "聊一聊学中文的方法。"]
    segs2 = _segments(client, lid)
    assert len(segs2) == 4 and [s["idx"] for s in segs2] == [0, 1, 2, 3]
    assert segs2[0]["text"] == "我今天想跟你们" and segs2[1]["text"] == "聊一聊学中文的方法。"
    assert [s["id"] for s in segs2[2:]] == [s["id"] for s in segs[1:]]
    assert abs(segs2[0]["end_s"] - segs2[1]["start_s"]) < 0.3
    assert segs2[0]["translation"] == "en:我今天想跟你们" and len(segs2[1]["ref_alignment_json"]) == 9
    assert client.app.state.files.clip_wav(lid, 3).exists()
    _assert_clips_consistent(client, lid, mp3=True)

    r = client.post(f"/segments/{segs2[0]['id']}/merge-next")
    assert r.status_code == 200 and r.json()["text"] == "我今天想跟你们聊一聊学中文的方法。"
    segs3 = _segments(client, lid)
    assert len(segs3) == 3 and segs3[0]["text"] == "我今天想跟你们聊一聊学中文的方法。"
    assert [s["idx"] for s in segs3] == [0, 1, 2] and [s["id"] for s in segs3[1:]] == [s["id"] for s in segs[1:]]
    assert len(segs3[0]["ref_alignment_json"]) == 16
    assert not client.app.state.files.clip_wav(lid, 3).exists()
    _assert_clips_consistent(client, lid, mp3=True)
    assert client.post(f"/segments/{segs3[-1]['id']}/merge-next").status_code == 409


def test_merge_middle_segment_shifts_later_clips_down(client, tmp_path):
    lid = _upload(client, tmp_path)
    _render_all_mp3(client, lid)
    segs = _segments(client, lid)
    assert client.post(f"/segments/{segs[0]['id']}/merge-next").status_code == 200
    segs2 = _segments(client, lid)
    assert [s["id"] for s in segs2] == [segs[0]["id"], segs[2]["id"]]
    assert segs2[0]["text"] == segs[0]["text"] + segs[1]["text"]
    _assert_clips_consistent(client, lid, mp3=True)
    assert client.post(f"/segments/{segs2[0]['id']}/merge-next").status_code == 200    # merges in the last one
    assert len(_segments(client, lid)) == 1
    _assert_clips_consistent(client, lid, mp3=True)


def test_resplit_rejects_bad_index(client, tmp_path):
    lid = _upload(client, tmp_path)
    seg = _segments(client, lid)[0]
    for k in (0, len(seg["text"]), 16):        # 16 leaves only "。" on the right
        assert client.post(f"/segments/{seg['id']}/resplit", json={"at_char_index": k}).status_code == 400, k
    assert len(_segments(client, lid)) == 3
    assert client.post("/segments/999/resplit", json={"at_char_index": 1}).status_code == 404
    assert client.post("/segments/999/merge-next").status_code == 404


def test_resplit_and_merge_anki_lesson(client, tmp_path):
    b64 = _b64(tmp_path, seconds=2.0)
    notes = [_dict(1, "你好世界。", "v.mp4 00:00:01.000", b64), _dict(2, "再见。", "v.mp4 00:00:05.000", b64)]
    jobs = client.post("/lessons/anki", json={"query_name": "q", "notes": notes}).json()["jobs"]
    assert wait_job(client, jobs[0]["job_id"])["status"] == "done"
    lid = jobs[0]["lesson_id"]
    segs = _segments(client, lid)
    start, end = segs[0]["start_s"], segs[0]["end_s"]
    r = client.post(f"/segments/{segs[0]['id']}/resplit", json={"at_char_index": 2})
    assert r.status_code == 200
    segs2 = _segments(client, lid)
    assert [s["text"] for s in segs2] == ["你好", "世界。", "再见。"]
    assert segs2[0]["start_s"] == start and segs2[1]["end_s"] == end          # Anki clips keep the note's span
    assert segs2[0]["end_s"] == segs2[1]["start_s"]
    _assert_clips_consistent(client, lid, mp3=True)
    assert client.post(f"/segments/{segs2[0]['id']}/merge-next").status_code == 200
    segs3 = _segments(client, lid)
    assert [s["text"] for s in segs3] == ["你好世界。", "再见。"]
    assert (segs3[0]["start_s"], segs3[0]["end_s"]) == (start, end)
    with Session(client.app.state.engine) as db:
        rows = db.exec(select(Segment).where(Segment.lesson_id == lid)).all()
    assert all(s.char_from is None and s.char_to is None for s in rows)
    _assert_clips_consistent(client, lid, mp3=True)
