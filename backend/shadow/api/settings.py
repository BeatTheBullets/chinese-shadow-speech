"""Settings the learner changes in the app rather than in config.toml: the YouTube cookies file."""
import contextlib
import os
import tempfile
from pathlib import Path
from fastapi import APIRouter, HTTPException, Request, Response, UploadFile
from shadow.ingest.youtube import COOKIES_NAME

router = APIRouter()
MAX_COOKIES_BYTES = 5 * 1024 * 1024
HEADERS = ("# Netscape HTTP Cookie File", "# HTTP Cookie File")
NOT_COOKIES = "That is not a cookies.txt file (it should start with '# Netscape HTTP Cookie File')."


def _path(request: Request) -> Path:
    return request.app.state.files.data_dir / COOKIES_NAME


def _is_cookies_file(data: bytes) -> bool:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    return first in HEADERS


@router.get("/settings/youtube-cookies")
def get_youtube_cookies(request: Request):
    return {"present": _path(request).is_file()}


@router.put("/settings/youtube-cookies")
async def put_youtube_cookies(request: Request, file: UploadFile):
    data = await file.read(MAX_COOKIES_BYTES + 1)
    if len(data) > MAX_COOKIES_BYTES or not _is_cookies_file(data):
        raise HTTPException(400, NOT_COOKIES)
    path = _path(request)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".youtube-cookies-", suffix=".tmp")     # mkstemp: owner-only
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    return {"present": True}


@router.delete("/settings/youtube-cookies", status_code=204)
def delete_youtube_cookies(request: Request):
    _path(request).unlink(missing_ok=True)
    return Response(status_code=204)
