from pathlib import Path
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


def test_every_ffmpeg_and_ffprobe_call_ignores_stdin(tmp_path, monkeypatch):
    """Under `make dev` ffmpeg would otherwise read the terminal: a stray `q` aborts an ingest."""
    import subprocess
    calls: list[list[str]] = []
    stdins: list[object] = []
    real_run = subprocess.run

    def spy(cmd, *a, **kw):
        calls.append(list(cmd)); stdins.append(kw.get("stdin"))
        return real_run(cmd, *a, **kw)
    monkeypatch.setattr(subprocess, "run", spy)
    src = make_tone_wav(tmp_path / "src.wav", 2.0)
    audio.normalise(src, tmp_path / "n.wav")
    audio.duration_s(src)
    audio.cut(src, tmp_path / "c.wav", 0.5, 1.5)
    audio.encode_opus(tmp_path / "c.wav", tmp_path / "c.opus")
    audio.encode_mp3(tmp_path / "c.wav", tmp_path / "c.mp3")
    assert {c[0] for c in calls} == {"ffmpeg", "ffprobe"} and len(calls) == 5
    assert all("-nostdin" in c for c in calls if c[0] == "ffmpeg"), [c for c in calls if "-nostdin" not in c]
    assert stdins == [subprocess.DEVNULL] * 5          # ffprobe has no -nostdin: its stdin is detached instead


def test_failed_mp3_encode_leaves_no_mp3(tmp_path, monkeypatch):
    """A failed (or interrupted) render must not leave a truncated mp3 that is then served as the clip."""
    import subprocess
    import pytest
    clip = make_tone_wav(tmp_path / "c.wav", 1.0)
    dst = tmp_path / "clips" / "0.mp3"
    dst.parent.mkdir()

    def half_written(cmd):
        Path(cmd[-1]).write_bytes(b"ID3 truncated")       # ffmpeg dies after writing part of its output
        raise subprocess.CalledProcessError(1, cmd)
    monkeypatch.setattr(audio, "_run", half_written)
    with pytest.raises(subprocess.CalledProcessError):
        audio.encode_mp3(clip, dst)
    assert list(dst.parent.iterdir()) == []


def test_mp3_render_replaces_an_existing_file_whole(tmp_path):
    clip = make_tone_wav(tmp_path / "c.wav", 1.0)
    dst = tmp_path / "0.mp3"
    dst.write_bytes(b"old")
    audio.encode_mp3(clip, dst)
    assert dst.stat().st_size > 1000 and abs(audio.duration_s(dst) - 1.0) < 0.1
    assert sorted(p.name for p in tmp_path.iterdir()) == ["0.mp3", "c.wav"]
