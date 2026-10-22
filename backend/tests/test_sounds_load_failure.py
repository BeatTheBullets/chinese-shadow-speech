import pytest

from tests.test_scoring_api import _first_segment, _post
from tests.helpers import make_tone_wav


def test_a_failed_lazy_sound_model_load_switches_sounds_off(client, tmp_path, monkeypatch):
    from shadow.scoring.sounds.charctc import CharCtc
    loads = []

    def failing_build(self):
        loads.append(1)
        raise MemoryError("not enough memory")
    monkeypatch.setattr(CharCtc, "_build", failing_build)
    chars = CharCtc("n", "r", "cpu")

    class LazySounds:
        def __init__(self): self.chars = chars

        def check(self, **kw):
            chars.sid("a")
    deps = client.app.state.deps
    deps.sounds = LazySounds()
    lid, seg = _first_segment(client, tmp_path)
    _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"])
    assert deps.sounds is None and deps.sounds_error == "not enough memory"
    _post(client, make_tone_wav(tmp_path / "t2.wav", 2.6), seg["id"])
    assert loads == [1]
    with pytest.raises(RuntimeError):
        chars.sid("a")                                   # fails fast, no second load
    assert loads == [1]
