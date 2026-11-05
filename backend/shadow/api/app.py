"""Release information: is a newer version of the app published on GitHub Releases? The app never updates itself;
the Library shows a banner with a download link."""
import json
import logging
import threading
import time
import urllib.request
from importlib.metadata import PackageNotFoundError, version
from fastapi import APIRouter, Request

log = logging.getLogger(__name__)
router = APIRouter()
TIMEOUT_S = 5
TTL_S = 24 * 3600
RETRY_S = 3600                    # a failed check (offline, private repo) is retried after an hour, not per request
_cache: tuple[float, dict] | None = None      # (monotonic time of the fetch, result)
_lock = threading.Lock()


def current_version() -> str | None:
    """None when the package metadata is missing: no banner then, rather than one for every release."""
    try:
        return version("shadow")
    except PackageNotFoundError:
        return None


def fetch_release(url: str) -> dict:
    """The releases API's JSON. Sends only a generic User-Agent, nothing about the user."""
    req = urllib.request.Request(url, headers={"User-Agent": f"chinese-shadow-speech/{current_version() or "unknown"}",
                                               "Accept": "application/vnd.github+json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:        # noqa: S310 (https URL from config)
        return json.load(r)


def parse_version(s: object) -> tuple[int, int, int] | None:
    if not isinstance(s, str):
        return None
    parts = s.strip().removeprefix("v").split(".")
    if len(parts) != 3 or not all(p.isascii() and p.isdigit() for p in parts):
        return None
    return int(parts[0]), int(parts[1]), int(parts[2])


def _latest(url: str) -> dict:
    global _cache
    with _lock:
        now = time.monotonic()
        if _cache is not None:
            ttl = TTL_S if _cache[1]["latest"] else RETRY_S
            if now - _cache[0] < ttl:
                return _cache[1]
        result = {"latest": None, "url": None}
        try:
            data = fetch_release(url)
            tag = str(data.get("tag_name") or "").strip().removeprefix("v")
            html_url = data.get("html_url")
            if parse_version(tag) is not None and isinstance(html_url, str) and html_url.startswith("https://"):
                result = {"latest": tag, "url": html_url}
        except Exception as e:  # noqa: BLE001
            log.info("update check failed: %s", e)
        _cache = (time.monotonic(), result)
        return result


@router.get("/app/update")
def update(request: Request):
    cur = current_version()
    found = _latest(request.app.state.settings.app.releases_api)
    cur_v, lat_v = parse_version(cur), parse_version(found["latest"])
    return {"current": cur, "latest": found["latest"], "url": found["url"],
            "newer": bool(lat_v and cur_v and lat_v > cur_v)}
