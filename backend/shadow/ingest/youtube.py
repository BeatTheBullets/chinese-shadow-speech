"""YouTube lessons (addendum spec §2): link parsing, metadata, Chinese subtitle choice and audio download behind a
`Downloader` protocol (yt-dlp in production, `FakeDownloader` in tests), and error messages the user can act on."""
from __future__ import annotations
import re
import shutil
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Protocol
from urllib.parse import parse_qs, urlparse

_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
                  "youtube-nocookie.com", "www.youtube-nocookie.com"}
_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
# Manual tracks first, simplified before traditional (zh-CN / zh-HK are the regional names of the same scripts), then
# auto-generated ones. No other language is ever chosen, so none is ever downloaded.
MANUAL_LANGS = ("zh-Hans", "zh-CN", "zh-Hant", "zh-TW", "zh-HK", "zh")
# Auto-generated: YouTube lists a machine translation into every language (zh-Hans, zh, ...) for each ASR track; only
# the track labelled "<code>-orig" is the speech actually recognised, so Chinese is accepted only as a `zh*-orig` key.
AUTO_ORIG_LANGS = ("zh-Hans-orig", "zh-orig")
SUBTITLE_EXTS = ("vtt", "srt")              # what parse_subtitles reads

COOKIES_HINT = "this video needs a cookies file — see Settings"
DENO_HINT = "install Deno (https://deno.com) — yt-dlp needs it for YouTube"
UPDATE_HINT = "update yt-dlp: `cd backend && uv lock --upgrade-package yt-dlp && uv sync --extra dev --extra models`"


class YoutubeError(RuntimeError):
    """A YouTube failure worded for the user; the lesson shows it as its error."""


def parse_video_id(url: str) -> str | None:
    """The 11-character id of a youtube.com/watch?v=…, youtu.be/… or youtube.com/shorts/… link, whatever else its
    query holds (&t=, &list=, ?si=); None for anything else."""
    s = url.strip()
    u = urlparse(s if "://" in s else f"https://{s}")
    host = (u.hostname or "").lower()
    parts = [p for p in u.path.split("/") if p]
    if host in _SHORT_HOSTS:
        cand = parts[0] if parts else ""
    elif host in _YOUTUBE_HOSTS and parts == ["watch"]:
        cand = parse_qs(u.query).get("v", [""])[0]
    elif host in _YOUTUBE_HOSTS and len(parts) >= 2 and parts[0] in ("shorts", "live", "embed"):
        cand = parts[1]
    else:
        return None
    return cand if _ID.fullmatch(cand) else None


def source_ref(video_id: str) -> str:
    return f"youtube::{video_id}"


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


@dataclass
class VideoInfo:
    video_id: str
    title: str
    channel: str
    upload_date: str | None = None
    duration: float | None = None
    chapters: list[dict] = field(default_factory=list)                  # {"title", "start_time", "end_time"}
    subtitles: dict[str, list[str]] = field(default_factory=dict)       # manual tracks: language -> formats
    automatic_captions: dict[str, list[str]] = field(default_factory=dict)
    is_live: bool = False


@dataclass(frozen=True)
class SubtitleChoice:
    lang: str
    auto: bool
    ext: str


def choose_subtitle(info: VideoInfo) -> SubtitleChoice | None:
    """The Chinese track to use (manual MANUAL_LANGS, else an original-language auto track) in a format the subtitle parser reads, or None."""
    orig = sorted((k for k in info.automatic_captions if k.startswith("zh") and k.endswith("-orig")),
                  key=lambda k: (k not in AUTO_ORIG_LANGS, k))
    for tracks, langs, auto in ((info.subtitles, MANUAL_LANGS, False), (info.automatic_captions, orig, True)):
        for lang in langs:
            ext = next((e for e in SUBTITLE_EXTS if e in tracks.get(lang, [])), None)
            if ext:
                return SubtitleChoice(lang, auto, ext)
    return None


def info_from_ytdlp(raw: dict[str, Any]) -> VideoInfo:
    """The fields shadow-speech uses from a yt-dlp info dict."""
    def tracks(d: dict | None) -> dict[str, list[str]]:
        return {lang: [t.get("ext", "") for t in ts or []] for lang, ts in (d or {}).items()}
    chapters = [{"title": c.get("title") or "", "start_time": float(c["start_time"]), "end_time": float(c["end_time"])}
                for c in raw.get("chapters") or []
                if c.get("start_time") is not None and c.get("end_time") is not None]
    return VideoInfo(
        video_id=raw.get("id", ""), title=raw.get("title") or raw.get("id", ""),
        channel=raw.get("channel") or raw.get("uploader") or "", upload_date=raw.get("upload_date"),
        duration=float(raw["duration"]) if raw.get("duration") else None, chapters=chapters,
        subtitles=tracks(raw.get("subtitles")), automatic_captions=tracks(raw.get("automatic_captions")),
        is_live=raw.get("live_status") == "is_live" or bool(raw.get("is_live")))


def readable_error(raw: str, warnings: Iterable[str] = ()) -> str:
    """yt-dlp's error message reworded into what the user can do about it (checked in this order: yt-dlp appends
    "Use --cookies" to private-video errors too). `warnings` are what yt-dlp reported on the way: a missing JavaScript
    runtime or a failed challenge is only ever a warning, followed by a vague "format not available" error."""
    m = raw.lower()
    w = " ".join(warnings).lower()
    if "try again later" in m or "rate-limit" in m:
        return "YouTube: YouTube is rate-limiting this computer — try again later"
    if any(k in m for k in ("private video", "video unavailable", "this video is unavailable", "has been removed",
                            "members-only", "this video is not available")):
        return "YouTube: this video is private or unavailable"
    if any(k in m for k in ("sign in to confirm", "age-restricted", "inappropriate for some users", "--cookies")):
        return f"YouTube: {COOKIES_HINT}"
    if any(k in m for k in ("unable to download webpage", "urlopen error", "timed out", "name resolution",
                            "network is unreachable", "connection reset", "connection refused")):
        return "YouTube: could not reach YouTube (network error) — check the connection and try again"
    deno_words = ("javascript runtime", "deno", "n challenge", "signature solving", "signature extraction")
    if any(k in m or k in w for k in deno_words):
        return f"YouTube: {DENO_HINT}"
    if any(k in m for k in ("unable to extract", "nsig", "signature", "http error 403", "please report this issue",
                            "requested format is not available", "only images are available")):
        if shutil.which("deno") is None:
            return f"YouTube: {DENO_HINT}"
        return f"YouTube: extraction failed, yt-dlp is probably outdated — {UPDATE_HINT}"
    first = raw.strip().splitlines()[0] if raw.strip() else "unknown error"
    return f"YouTube download failed: {first}"


class Downloader(Protocol):
    def probe(self, url: str) -> VideoInfo: ...
    def download_audio(self, url: str, dest_dir: Path) -> Path: ...
    def fetch_subtitle(self, url: str, choice: SubtitleChoice) -> str: ...


class _Warnings:
    """yt-dlp logger: keeps warnings (where it reports a missing JavaScript runtime) and drops everything else."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def debug(self, msg: str) -> None: ...
    def info(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)


class YtDlpDownloader:
    """yt-dlp's Python API. Only the chosen Chinese subtitle track is ever fetched."""

    def __init__(self, cookies_file: str = ""):
        self.cookies_file = cookies_file
        self._subs: dict[str, dict[str, Any]] = {}       # video id -> subtitle maps from probe(), until fetched

    def _opts(self, **extra: Any) -> dict[str, Any]:
        opts: dict[str, Any] = {"quiet": True, "noprogress": True, "noplaylist": True, "color": "no_color",
                                "cachedir": False, **extra}
        if self.cookies_file:
            opts["cookiefile"] = str(Path(self.cookies_file).expanduser())
        return opts

    @contextmanager
    def _ydl(self, **extra: Any) -> Iterator[tuple[Any, _Warnings]]:
        """A YoutubeDL on a temporary copy of the cookies file: yt-dlp saves cookies back on exit and must never
        rewrite the user's file."""
        import yt_dlp
        log = _Warnings()
        with tempfile.TemporaryDirectory(prefix="shadow-yt-") as tmp:
            opts = self._opts(logger=log, **extra)
            if "cookiefile" in opts:
                try:
                    shutil.copyfile(opts["cookiefile"], Path(tmp) / "cookies.txt")
                except OSError as e:
                    raise YoutubeError(f"YouTube: cannot read the cookies file: {e}") from e
                opts["cookiefile"] = str(Path(tmp) / "cookies.txt")
            with yt_dlp.YoutubeDL(opts) as ydl:
                yield ydl, log

    def probe(self, url: str) -> VideoInfo:
        import yt_dlp
        log = _Warnings()
        try:
            with self._ydl(skip_download=True) as (ydl, log):
                raw = ydl.extract_info(url, download=False)
        except yt_dlp.utils.YoutubeDLError as e:
            raise YoutubeError(readable_error(str(e), log.warnings)) from e
        info = info_from_ytdlp(raw)
        self._subs[info.video_id] = {k: raw.get(k) for k in ("subtitles", "automatic_captions")}
        return info

    def download_audio(self, url: str, dest_dir: Path) -> Path:
        import yt_dlp
        dest_dir.mkdir(parents=True, exist_ok=True)
        # Falls back to a muxed format when YouTube offers no audio-only one; normalising drops the video.
        extra = {"format": "bestaudio/best", "outtmpl": {"default": str(dest_dir.resolve() / "audio.%(ext)s")}}
        log = _Warnings()
        try:
            with self._ydl(**extra) as (ydl, log):
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.YoutubeDLError as e:
            raise YoutubeError(readable_error(str(e), log.warnings)) from e
        paths = [Path(d["filepath"]) for d in info.get("requested_downloads") or [] if d.get("filepath")]
        if not paths or not paths[0].exists():
            raise YoutubeError("YouTube download failed: yt-dlp wrote no audio file")
        return paths[0]

    def fetch_subtitle(self, url: str, choice: SubtitleChoice) -> str:
        import yt_dlp
        log = _Warnings()
        try:
            with self._ydl(skip_download=True) as (ydl, log):
                key = parse_video_id(url) or url
                maps = self._subs.pop(key, None) or ydl.extract_info(url, download=False)
                tracks = (maps.get("automatic_captions") if choice.auto else maps.get("subtitles")) or {}
                track = next((t for t in tracks.get(choice.lang, []) if t.get("ext") == choice.ext), None)
                if track is None:
                    raise YoutubeError(f"YouTube no longer offers the {choice.lang} subtitles")
                return ydl.urlopen(track["url"]).read().decode("utf-8-sig", errors="replace")
        except yt_dlp.utils.YoutubeDLError as e:
            raise YoutubeError(readable_error(str(e), log.warnings)) from e


class FakeDownloader:
    """Tests: fixed metadata, `audio` copied as the download, subtitle text per (lang, auto). `error` is raised by
    probe(), where yt-dlp reports private, sign-in and network failures."""

    def __init__(self, info: VideoInfo, audio: Path, subs: dict[tuple[str, bool], str] | None = None,
                 error: Exception | None = None):
        self.info, self.audio, self.subs, self.error = info, audio, subs or {}, error
        self.fetched: list[tuple[str, bool]] = []
        self.downloads = 0

    def probe(self, url: str) -> VideoInfo:
        if self.error is not None:
            raise self.error
        return self.info

    def download_audio(self, url: str, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        self.downloads += 1
        dst = dest_dir / f"audio{self.audio.suffix}"
        shutil.copyfile(self.audio, dst)
        return dst

    def fetch_subtitle(self, url: str, choice: SubtitleChoice) -> str:
        self.fetched.append((choice.lang, choice.auto))
        if (choice.lang, choice.auto) not in self.subs:
            raise YoutubeError(f"YouTube no longer offers the {choice.lang} subtitles")
        return self.subs[(choice.lang, choice.auto)]
