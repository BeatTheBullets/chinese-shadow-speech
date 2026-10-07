from sqlmodel import Session
from shadow.ingest.youtube import FakeDownloader, VideoInfo, YoutubeError, readable_error
from shadow.store.models import Lesson
from tests.conftest import LESSON_TEXT, wait_job
from tests.helpers import make_tone_wav

VID = "abcDEF12345"
URL = f"https://www.youtube.com/watch?v={VID}&t=42s"


def _vtt(cues):
    out = "WEBVTT\n\n"
    for a, b, t in cues:
        out += f"00:00:{a:06.3f} --> 00:00:{b:06.3f}\n{t}\n\n"
    return out


def _fake(client, tmp_path, manual=None, auto=None, subs=None, error=None, duration=8.0, chapters=None, is_live=False):
    info = VideoInfo(video_id=VID, title="學中文的方法", channel="老師頻道", upload_date="20260901", duration=duration,
                     chapters=chapters or [], subtitles=manual or {}, automatic_captions=auto or {}, is_live=is_live)
    fake = FakeDownloader(info, make_tone_wav(tmp_path / "yt.wav", 8.0), subs, error)
    client.app.state.deps.downloader = fake
    return fake


def _lesson(client, lid):
    with Session(client.app.state.engine) as db:
        return db.get(Lesson, lid)


def test_youtube_lesson_takes_text_from_chinese_subtitles(client, tmp_path):
    fake = _fake(client, tmp_path, manual={"zh-Hant": ["vtt"], "en": ["vtt"]},
                 subs={("zh-Hant", False): _vtt(LESSON_TEXT)})
    r = client.post("/lessons/youtube", json={"url": URL})
    assert r.status_code == 202
    assert wait_job(client, r.json()["job_id"])["status"] == "done"
    lesson = _lesson(client, r.json()["lesson_id"])
    assert (lesson.status, lesson.source_type, lesson.source_ref) == ("ready", "youtube", f"youtube::{VID}")
    assert (lesson.title, lesson.speaker) == ("学中文的方法", "老师频道")
    meta = lesson.meta_json
    assert meta["url"] == f"https://www.youtube.com/watch?v={VID}" and meta["channel"] == "老師頻道"
    assert (meta["upload_date"], meta["duration"], meta["chapters"]) == ("20260901", 8.0, [])
    assert meta["subtitle_track"] == "zh-Hant" and meta["subtitle_match"] == 1.0
    assert fake.fetched == [("zh-Hant", False)]                        # English is never fetched
    segs = client.get(f"/lessons/{lesson.id}").json()["segments"]
    assert [s["text"] for s in segs] == [t for _, _, t in LESSON_TEXT]


def test_youtube_lesson_without_chinese_subtitles_uses_the_asr_text(client, tmp_path):
    fake = _fake(client, tmp_path, manual={"en": ["vtt"]})
    r = client.post("/lessons/youtube", json={"url": f"https://youtu.be/{VID}"}).json()
    wait_job(client, r["job_id"])
    lesson = _lesson(client, r["lesson_id"])
    assert lesson.status == "ready" and fake.fetched == []
    assert "subtitle_track" not in lesson.meta_json and "subtitle_match" not in lesson.meta_json


def test_an_unreadable_subtitle_track_falls_back_to_the_asr(client, tmp_path):
    fake = _fake(client, tmp_path, auto={"zh-Hans-orig": ["vtt"]})       # listed, but fetching it fails
    r = client.post("/lessons/youtube", json={"url": URL}).json()
    wait_job(client, r["job_id"])
    lesson = _lesson(client, r["lesson_id"])
    assert lesson.status == "ready" and fake.fetched == [("zh-Hans-orig", True)]
    assert "zh-Hans-orig" in lesson.meta_json["subtitle_ignored"]


def test_adding_the_same_video_again_returns_its_lesson_without_a_job(client, tmp_path):
    fake = _fake(client, tmp_path)
    first = client.post("/lessons/youtube", json={"url": URL}).json()
    wait_job(client, first["job_id"])
    again = client.post("/lessons/youtube", json={"url": f"https://m.youtube.com/watch?v={VID}&list=PL1&index=2"})
    assert again.status_code == 200 and again.json() == {"job_id": None, "lesson_id": first["lesson_id"]}
    assert fake.downloads == 1 and len(client.get("/lessons").json()) == 1


def test_a_failed_video_is_reingested_when_added_again(client, tmp_path):
    fake = _fake(client, tmp_path, error=YoutubeError(readable_error("Sign in to confirm your age. Use --cookies")))
    first = client.post("/lessons/youtube", json={"url": URL}).json()
    assert wait_job(client, first["job_id"])["status"] == "error"
    lesson = _lesson(client, first["lesson_id"])
    assert (lesson.status, lesson.error) == ("error", "YouTube: this video needs a cookies file — see Settings")
    fake.error = None
    second = client.post("/lessons/youtube", json={"url": URL})
    assert second.status_code == 202 and second.json()["job_id"]
    assert wait_job(client, second.json()["job_id"])["status"] == "done"
    assert client.get(f"/lessons/{first['lesson_id']}").status_code == 404
    assert [l["status"] for l in client.get("/lessons").json()] == ["ready"]


def test_a_video_over_the_length_limit_is_refused_readably(client, tmp_path):
    fake = _fake(client, tmp_path, duration=91 * 60)
    r = client.post("/lessons/youtube", json={"url": URL}).json()
    assert wait_job(client, r["job_id"])["status"] == "error"
    error = _lesson(client, r["lesson_id"]).error
    assert "91 min" in error and "max_minutes" in error and fake.downloads == 0


def test_a_live_stream_is_refused_readably(client, tmp_path):
    fake = _fake(client, tmp_path, duration=None, is_live=True)
    r = client.post("/lessons/youtube", json={"url": URL}).json()
    assert wait_job(client, r["job_id"])["status"] == "error"
    assert "live" in _lesson(client, r["lesson_id"]).error and fake.downloads == 0


def test_an_unknown_duration_proceeds_but_the_downloaded_audio_is_still_limited(client, tmp_path):
    client.app.state.settings.youtube.max_minutes = 0                    # nothing fits; the fake audio is 8 s
    fake = _fake(client, tmp_path, duration=None)
    r = client.post("/lessons/youtube", json={"url": URL}).json()
    assert wait_job(client, r["job_id"])["status"] == "error"
    assert fake.downloads == 1 and "max_minutes" in _lesson(client, r["lesson_id"]).error


def test_the_downloader_gets_the_canonical_url_titles_are_simplified_and_downloads_are_removed(client, tmp_path):
    seen = []

    class Spy(FakeDownloader):
        def probe(self, url):
            seen.append(url)
            return super().probe(url)

        def download_audio(self, url, dest_dir):
            seen.append(url)
            return super().download_audio(url, dest_dir)

    fake = _fake(client, tmp_path, chapters=[{"title": "開始", "start_time": 0.0, "end_time": 8.0}])
    spy = Spy(fake.info, fake.audio)
    client.app.state.deps.downloader = spy
    r = client.post("/lessons/youtube", json={"url": URL}).json()
    assert wait_job(client, r["job_id"])["status"] == "done"
    assert seen == [f"https://www.youtube.com/watch?v={VID}"] * 2
    assert _lesson(client, r["lesson_id"]).meta_json["chapters"][0]["title"] == "开始"
    assert not (client.app.state.files.lesson_dir(r["lesson_id"]) / "download").exists()


def test_bad_links_and_disabled_youtube_are_400(client):
    assert client.post("/lessons/youtube", json={"url": "https://vimeo.com/1"}).status_code == 400
    client.app.state.settings.youtube.enabled = False
    r = client.post("/lessons/youtube", json={"url": URL})
    assert r.status_code == 400 and "enabled" in r.json()["detail"]


def test_ingest_youtube_reports_the_download_stage_first(data_dir, fake_transcript, tmp_path):
    from shadow.ingest.pipeline import ingest_youtube
    from tests.test_pipeline import _setup
    deps, engine, lid = _setup(data_dir, fake_transcript)
    deps.downloader = FakeDownloader(VideoInfo(video_id=VID, title="t", channel="c"), make_tone_wav(tmp_path / "a.wav", 8.0))
    stages = []
    ingest_youtube(deps, engine, lid, URL, lambda s, f: stages.append(s))
    assert list(dict.fromkeys(stages))[:3] == ["download", "normalise", "transcribe"] and stages[-1] == "done"
