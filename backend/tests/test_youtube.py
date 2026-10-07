import pytest
from shadow.ingest.youtube import (SubtitleChoice, VideoInfo, YtDlpDownloader, choose_subtitle, info_from_ytdlp,
                                   parse_video_id, readable_error, source_ref, watch_url)

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VID}",
    f"https://youtube.com/watch?v={VID}&t=42s",
    f"https://m.youtube.com/watch?v={VID}&list=PL123&index=2",
    f"https://www.youtube.com/watch?feature=share&v={VID}",
    f"youtube.com/watch?v={VID}",
    f"https://youtu.be/{VID}",
    f"https://youtu.be/{VID}?si=abc&t=10",
    f"https://www.youtube.com/shorts/{VID}",
    f"https://youtube.com/shorts/{VID}?feature=share",
    f"  https://www.youtube.com/watch?v={VID}  ",
])
def test_parse_video_id_accepts_watch_short_and_shorts_links(url):
    assert parse_video_id(url) == VID


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/playlist?list=PL123", "https://vimeo.com/123", "https://www.youtube.com/watch?v=short",
    "https://youtu.be/", "not a url", "", f"https://evil.example/watch?v={VID}",
])
def test_parse_video_id_rejects_other_links(url):
    assert parse_video_id(url) is None


def test_refs():
    assert source_ref(VID) == f"youtube::{VID}"
    assert watch_url(VID) == f"https://www.youtube.com/watch?v={VID}"


def _info(manual=None, auto=None):
    return VideoInfo(video_id=VID, title="t", channel="c", subtitles=manual or {}, automatic_captions=auto or {})


@pytest.mark.parametrize("manual,auto,want", [
    ({"zh-Hans": ["vtt"], "zh-Hant": ["vtt"], "en": ["vtt"]}, {}, SubtitleChoice("zh-Hans", False, "vtt")),
    ({"zh-CN": ["vtt"]}, {}, SubtitleChoice("zh-CN", False, "vtt")),
    ({"zh-TW": ["vtt"], "en": ["vtt"]}, {"zh-Hans": ["vtt"]}, SubtitleChoice("zh-TW", False, "vtt")),
    ({"zh-Hant": ["srv3", "srt"]}, {}, SubtitleChoice("zh-Hant", False, "srt")),
    ({"zh": ["vtt"]}, {"zh-Hans": ["vtt"]}, SubtitleChoice("zh", False, "vtt")),
    ({"en": ["vtt"]}, {"zh-Hans": ["json3", "vtt"], "zh": ["vtt"]}, SubtitleChoice("zh-Hans", True, "vtt")),
    ({}, {"zh": ["vtt"], "en": ["vtt"]}, SubtitleChoice("zh", True, "vtt")),
    ({"en": ["vtt"], "ja": ["vtt"]}, {"en": ["vtt"]}, None),
    ({"zh-Hans": ["json3"]}, {}, None),
])
def test_choose_subtitle_prefers_manual_simplified_and_never_other_languages(manual, auto, want):
    assert choose_subtitle(_info(manual, auto)) == want


def test_info_from_ytdlp_maps_metadata_chapters_and_tracks():
    raw = {"id": VID, "title": "學中文", "uploader": "老師", "upload_date": "20260901", "duration": 754,
           "chapters": [{"title": "開始", "start_time": 0.0, "end_time": 300.0}, {"title": "x", "start_time": None}],
           "subtitles": {"zh-Hant": [{"ext": "vtt", "url": "u1"}, {"ext": "srv3", "url": "u2"}]},
           "automatic_captions": {"zh-Hans": [{"ext": "vtt", "url": "u3"}]}, "live_status": "not_live"}
    info = info_from_ytdlp(raw)
    assert (info.video_id, info.title, info.channel, info.upload_date, info.duration) == (VID, "學中文", "老師", "20260901", 754.0)
    assert info.chapters == [{"title": "開始", "start_time": 0.0, "end_time": 300.0}]
    assert info.subtitles == {"zh-Hant": ["vtt", "srv3"]} and info.automatic_captions == {"zh-Hans": ["vtt"]}
    assert info.is_live is False
    assert info_from_ytdlp({"id": VID, "channel": "频道", "uploader": "u"}).channel == "频道"
    assert info_from_ytdlp({"id": VID, "live_status": "is_live"}).is_live is True


@pytest.mark.parametrize("raw,want", [
    ("ERROR: [youtube] x: Private video. Sign in if you've been granted access to this video. Use --cookies-from-browser or --cookies for the authentication.", "private or unavailable"),
    ("ERROR: [youtube] x: Video unavailable. This video has been removed by the uploader", "private or unavailable"),
    ("ERROR: [youtube] x: Sign in to confirm your age. This video may be inappropriate for some users. Use --cookies", "this video needs a cookies file — see Settings"),
    ("ERROR: [youtube] x: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies", "this video needs a cookies file — see Settings"),
    ("ERROR: [youtube] x: Unable to download webpage: <urlopen error [Errno -3] Temporary failure in name resolution>", "network"),
    ("ERROR: [youtube] x: Unable to extract initial player response; please report this issue", "uv lock --upgrade-package yt-dlp"),
    ("ERROR: [youtube] x: nsig extraction failed: Some formats may be missing", "uv lock --upgrade-package yt-dlp"),
    ("ERROR: something new", "YouTube download failed: ERROR: something new"),
])
def test_readable_error(raw, want):
    assert want in readable_error(raw)


def test_ytdlp_options_carry_the_cookies_file_only_when_set(tmp_path):
    assert "cookiefile" not in YtDlpDownloader()._opts()
    opts = YtDlpDownloader(str(tmp_path / "c.txt"))._opts(skip_download=True)
    assert opts["cookiefile"] == str(tmp_path / "c.txt") and opts["skip_download"] is True and opts["noplaylist"] is True


@pytest.mark.parametrize("raw", [
    "ERROR: [youtube] x: No supported JavaScript runtime could be found. Only deno is enabled by default",
    "WARNING: [youtube] x: n challenge solving failed: Some formats may be missing",
    "ERROR: [youtube] x: Signature extraction failed: Some formats may be missing",
])
def test_readable_error_points_at_deno_before_the_update_hint(raw):
    msg = readable_error(raw)
    assert "install Deno (https://deno.com)" in msg and "uv lock" not in msg
