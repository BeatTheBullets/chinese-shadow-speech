from __future__ import annotations
import json
import os
import subprocess
import uuid
from pathlib import Path
import numpy as np
import soundfile as sf

SR = 16000


# ffmpeg reads keys from the terminal it inherits (a stray `q` under `make dev` aborts an ingest): every call
# gets -nostdin (ffmpeg only; ffprobe rejects the flag) and a detached stdin.
def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def normalise(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-nostdin", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(dst)])


def duration_s(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        check=True, stdin=subprocess.DEVNULL, capture_output=True, text=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def cut(src: Path, dst: Path, start_s: float, end_s: float) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-nostdin", "-y", "-ss", f"{start_s:.3f}", "-to", f"{end_s:.3f}", "-i", str(src),
          "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(dst)])


def encode_opus(src_wav: Path, dst: Path) -> None:
    _run(["ffmpeg", "-nostdin", "-y", "-i", str(src_wav), "-c:a", "libopus", "-b:a", "48k", str(dst)])


def encode_mp3(src_wav: Path, dst: Path) -> None:
    """Rendered on demand and then served as is, so it appears only whole: encoded to a temporary name in the
    same directory and moved into place; a failed or concurrent render never leaves a truncated mp3."""
    tmp = dst.with_name(f"{dst.stem}.{uuid.uuid4().hex[:8]}.part.mp3")
    try:
        _run(["ffmpeg", "-nostdin", "-y", "-i", str(src_wav), "-c:a", "libmp3lame", "-q:a", "4", str(tmp)])
        os.replace(tmp, dst)
    finally:
        tmp.unlink(missing_ok=True)


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    data, sr = sf.read(path, dtype="float32", always_2d=False)
    if data.ndim == 2:
        data = data.mean(axis=1)
    return data, sr


def write_wav(path: Path, samples: np.ndarray, sr: int = SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, samples.astype("float32"), sr, subtype="PCM_16")
