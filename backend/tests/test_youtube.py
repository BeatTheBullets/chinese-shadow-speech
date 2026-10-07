import io
from pathlib import Path

import pytest
from shadow.ingest.youtube import (FakeDownloader, SubtitleChoice, VideoInfo, YoutubeError, YtDlpDownloader, choose_subtitle, info_from_ytdlp,
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
    f"https://www.youtube.com/embed/{VID}",
    f"https://www.youtube-nocookie.com/embed/{VID}?start=3",
    f"https://www.youtube.com/watch/?v={VID}",
    f"https://music.youtube.com/watch?v={VID}",
    f"https://www.youtube.com/live/{VID}?feature=share",
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
    ({"en": ["vtt"]}, {"zh-Hans-orig": ["json3", "vtt"], "zh-Hans": ["vtt"]}, SubtitleChoice("zh-Hans-orig", True, "vtt")),
    ({}, {"zh-orig": ["vtt"], "zh": ["vtt"], "en": ["vtt"]}, SubtitleChoice("zh-orig", True, "vtt")),
    ({}, {"en-orig": ["vtt"], "en": ["vtt"], "zh-Hans": ["vtt"]}, None),
    ({}, {"zh-Hans": ["vtt"], "zh": ["vtt"]}, None),
    ({}, {"zh-Hans-orig": ["vtt"], "zh-Hans": ["vtt"], "en": ["vtt"]}, SubtitleChoice("zh-Hans-orig", True, "vtt")),
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
def test_readable_error(raw, want, monkeypatch):
    monkeypatch.setattr("shadow.ingest.youtube.shutil.which", lambda _: "/usr/bin/deno")
    assert want in readable_error(raw)


def test_ytdlp_options_carry_the_cookies_file_only_when_set(tmp_path):
    assert "cookiefile" not in YtDlpDownloader()._opts()
    opts = YtDlpDownloader(str(tmp_path / "c.txt"))._opts(skip_download=True)
    assert opts["cookiefile"] == str(tmp_path / "c.txt") and opts["skip_download"] is True and opts["noplaylist"] is True


@pytest.mark.parametrize("warning", [
    "[youtube] x: No supported JavaScript runtime could be found. Only deno is enabled by default",
    "[youtube] x: n challenge solving failed: Some formats may be missing",
    "[youtube] x: Signature solving failed: Some formats may be missing",
])
def test_readable_error_points_at_deno_when_yt_dlp_warned_about_it(warning, monkeypatch):
    monkeypatch.setattr("shadow.ingest.youtube.shutil.which", lambda _: "/usr/bin/deno")
    msg = readable_error("ERROR: [youtube] x: Requested format is not available", [warning])
    assert "install Deno (https://deno.com)" in msg and "uv lock" not in msg


def test_readable_error_points_at_deno_when_extraction_fails_and_deno_is_missing(monkeypatch):
    raw = "ERROR: [youtube] x: Only images are available for download"
    monkeypatch.setattr("shadow.ingest.youtube.shutil.which", lambda _: None)
    assert "install Deno" in readable_error(raw)
    monkeypatch.setattr("shadow.ingest.youtube.shutil.which", lambda _: "/usr/bin/deno")
    assert "uv lock --upgrade-package yt-dlp" in readable_error(raw)


@pytest.mark.parametrize("raw,want", [
    ("ERROR: [youtube] x: HTTP Error 403: Forbidden", "uv lock --upgrade-package yt-dlp"),
    ("ERROR: [youtube] x: Video unavailable. This content isn't available, try again later.", "rate-limiting"),
])
def test_readable_error_http_403_and_rate_limit(raw, want, monkeypatch):
    monkeypatch.setattr("shadow.ingest.youtube.shutil.which", lambda _: "/usr/bin/deno")
    assert want in readable_error(raw)


class _FakeYDL:
    """Stands in for yt_dlp.YoutubeDL: records its options, serves a canned info dict, never touches the network."""
    instances: list = []
    info: dict = {}
    urlopen_error: Exception | None = None

    def __init__(self, params):
        self.params = params
        self.cookie_text = None
        if params.get("cookiefile"):
            with open(params["cookiefile"]) as f:
                self.cookie_text = f.read()
        _FakeYDL.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=True):
        if download:
            Path(self.params["outtmpl"]["default"].replace("%(ext)s", "m4a")).write_bytes(b"x")
        return self.info

    def urlopen(self, url):
        if _FakeYDL.urlopen_error:
            raise _FakeYDL.urlopen_error
        return io.BytesIO("WEBVTT\n".encode("utf-8-sig"))


@pytest.fixture
def fake_ydl(monkeypatch):
    import yt_dlp
    _FakeYDL.instances, _FakeYDL.urlopen_error = [], None
    _FakeYDL.info = {"id": VID, "title": "t", "requested_downloads": []}
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _FakeYDL)
    return _FakeYDL


def test_download_audio_options(tmp_path, fake_ydl):
    cookies = tmp_path / "c.txt"
    cookies.write_text("# Netscape\n")
    dest = tmp_path / "out"
    fake_ydl.info["requested_downloads"] = [{"filepath": str(dest / "audio.m4a")}]
    assert YtDlpDownloader(str(cookies)).download_audio(watch_url(VID), dest) == dest / "audio.m4a"
    p = fake_ydl.instances[0].params
    assert p["format"] == "bestaudio/best" and p["noplaylist"] is True and not p.get("writesubtitles")
    assert p["outtmpl"]["default"] == str(dest.resolve() / "audio.%(ext)s")
    assert p["color"] == "no_color" and p["cachedir"] is False and "logger" in p
    assert p["cookiefile"] != str(cookies) and fake_ydl.instances[0].cookie_text == "# Netscape\n"   # a copy
    assert not Path(p["cookiefile"]).exists() and cookies.read_text() == "# Netscape\n"
    fake_ydl.instances.clear()
    fake_ydl.info["requested_downloads"] = [{"filepath": str(dest / "audio.m4a")}]
    YtDlpDownloader().download_audio(watch_url(VID), dest)
    assert "cookiefile" not in fake_ydl.instances[0].params


def test_fetch_subtitle_uses_probed_tracks_once_and_wraps_network_errors(fake_ydl):
    from yt_dlp.networking.exceptions import TransportError
    fake_ydl.info = {"id": VID, "subtitles": {"zh-Hans": [{"ext": "vtt", "url": "u"}]}}
    d, choice = YtDlpDownloader(), SubtitleChoice("zh-Hans", False, "vtt")
    d.probe(watch_url(VID))
    assert d._subs.keys() == {VID}
    assert d.fetch_subtitle(watch_url(VID), choice) == "WEBVTT\n" and d._subs == {}
    fake_ydl.urlopen_error = TransportError("connection reset")
    with pytest.raises(YoutubeError, match="network"):
        d.fetch_subtitle(watch_url(VID), choice)


def test_fake_downloader(tmp_path):
    audio = tmp_path / "a.wav"
    audio.write_bytes(b"x")
    f = FakeDownloader(_info(), audio, {("zh", False): "T"})
    assert f.probe("u") is f.info and f.download_audio("u", tmp_path / "d").read_bytes() == b"x" and f.downloads == 1
    assert f.fetch_subtitle("u", SubtitleChoice("zh", False, "vtt")) == "T"
    with pytest.raises(YoutubeError):
        f.fetch_subtitle("u", SubtitleChoice("zh", True, "vtt"))
    assert f.fetched == [("zh", False), ("zh", True)]
    with pytest.raises(ValueError):
        FakeDownloader(_info(), audio, error=ValueError("x")).probe("u")
