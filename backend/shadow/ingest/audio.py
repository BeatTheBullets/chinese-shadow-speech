from __future__ import annotations
import json
import subprocess
from pathlib import Path
import numpy as np
import soundfile as sf

SR = 16000


def _run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def normalise(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(dst)])


def duration_s(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    return float(json.loads(out)["format"]["duration"])


def cut(src: Path, dst: Path, start_s: float, end_s: float) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-ss", f"{start_s:.3f}", "-to", f"{end_s:.3f}", "-i", str(src),
          "-ac", "1", "-ar", str(SR), "-c:a", "pcm_s16le", str(dst)])


def encode_opus(src_wav: Path, dst: Path) -> None:
    _run(["ffmpeg", "-y", "-i", str(src_wav), "-c:a", "libopus", "-b:a", "48k", str(dst)])


def encode_mp3(src_wav: Path, dst: Path) -> None:
    _run(["ffmpeg", "-y", "-i", str(src_wav), "-c:a", "libmp3lame", "-q:a", "4", str(dst)])


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    data, sr = sf.read(path, dtype="float32", always_2d=False)
    if data.ndim == 2:
        data = data.mean(axis=1)
    return data, sr


def write_wav(path: Path, samples: np.ndarray, sr: int = SR) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, samples.astype("float32"), sr, subtype="PCM_16")
