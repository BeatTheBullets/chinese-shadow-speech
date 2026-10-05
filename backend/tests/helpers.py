from pathlib import Path
import numpy as np
import soundfile as sf


def make_tone_wav(path: Path, seconds: float, sr: int = 16000, freq: float = 220.0) -> Path:
    t = np.arange(int(seconds * sr)) / sr
    sf.write(path, (0.3 * np.sin(2 * np.pi * freq * t)).astype("float32"), sr)
    return path
