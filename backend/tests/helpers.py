from pathlib import Path
import numpy as np
import soundfile as sf


def make_tone_wav(path: Path, seconds: float, sr: int = 16000, freq: float = 220.0) -> Path:
    t = np.arange(int(seconds * sr)) / sr
    sf.write(path, (0.3 * np.sin(2 * np.pi * freq * t)).astype("float32"), sr)
    return path


def voice(contours: list[tuple[float, float]], syl_s: float = 0.25, sr: int = 16000, lead_s: float = 0.0) -> np.ndarray:
    """A harmonic test 'voice': per syllable the pitch moves linearly from a to b Hz (continuous phase), with `lead_s`
    of silence on each side. Pitch trackers follow it like a sustained vowel."""
    f = np.concatenate([np.linspace(a, b, int(syl_s * sr), endpoint=False) for a, b in contours])
    phase = 2 * np.pi * np.cumsum(f) / sr
    x = sum(np.sin(k * phase) / k for k in range(1, 6)) * 0.2
    pad = np.zeros(int(lead_s * sr))
    return np.concatenate([pad, x, pad]).astype("float32")
