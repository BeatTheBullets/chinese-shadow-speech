import numpy as np
import soundfile as sf
from shadow.ingest import audio
from tests.helpers import make_tone_wav


def test_normalise_to_16k_mono(tmp_path):
    src = tmp_path / "in.wav"
    t = np.arange(44100) / 44100
    stereo = np.stack([np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 220 * t)], axis=1).astype("float32")
    sf.write(src, stereo, 44100)
    dst = tmp_path / "out.wav"
    audio.normalise(src, dst)
    info = sf.info(dst)
    assert info.samplerate == 16000 and info.channels == 1 and info.subtype == "PCM_16"
    assert abs(audio.duration_s(dst) - 1.0) < 0.02


def test_cut_and_encode(tmp_path):
    src = make_tone_wav(tmp_path / "src.wav", 3.0)
    clip = tmp_path / "c.wav"
    audio.cut(src, clip, 1.0, 2.5)
    assert abs(audio.duration_s(clip) - 1.5) < 0.02
    audio.encode_opus(clip, tmp_path / "c.opus")
    audio.encode_mp3(clip, tmp_path / "c.mp3")
    assert (tmp_path / "c.opus").stat().st_size > 0 and (tmp_path / "c.mp3").stat().st_size > 0


def test_read_write_wav_roundtrip(tmp_path):
    x = (0.1 * np.random.randn(16000)).astype("float32")
    audio.write_wav(tmp_path / "r.wav", x)
    y, sr = audio.read_wav(tmp_path / "r.wav")
    assert sr == 16000 and y.shape == x.shape and np.max(np.abs(y - x)) < 1e-3
