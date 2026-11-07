import io
import sys
import types

import pytest

from shadow.config import SegmentationCfg
from shadow.ingest.punct import SherpaPunctuator, punctuate_timed
from shadow.ingest.text import is_punct

CFG = SegmentationCfg()


class MarkEvery:
    """Fake punctuator: a comma after every 5th character and a full stop at the end."""
    def __init__(self):
        self.calls: list[str] = []

    def punctuate(self, text: str) -> str:
        self.calls.append(text)
        out = "".join(ch + ("，" if (i + 1) % 5 == 0 else "") for i, ch in enumerate(text))
        return out + "。"


def _speech(s: str) -> str:
    return "".join(ch for ch in s if not is_punct(ch))


def _ts(n: int, gaps: dict[int, int] | None = None) -> list[list[int]]:
    """100 ms per char; `gaps[k]` extra ms of silence after char k."""
    out, t = [], 0
    for k in range(n):
        out.append([t, t + 100])
        t += 100 + (gaps or {}).get(k, 0)
    return out


def test_punctuate_timed_keeps_characters_and_order():
    text = "我是学生我喜欢学习中文每天都说"
    out = punctuate_timed(text, _ts(len(text)), MarkEvery(), CFG)
    assert _speech(out) == text
    assert "，" in out and "。" in out


def test_chunks_are_at_most_150_chars_and_cut_at_largest_gaps():
    text = "".join(chr(0x4e00 + i) for i in range(400))
    gaps = {99: 800, 230: 900, 310: 700}              # the 3 largest gaps, one every ~100 chars
    fake = MarkEvery()
    out = punctuate_timed(text, _ts(400, gaps), fake, CFG)
    assert all(len(c) <= 150 for c in fake.calls)
    assert "".join(fake.calls) == text
    assert _speech(out) == text
    assert [len(c) for c in fake.calls] == [100, 131, 80, 89]


def test_short_text_is_one_chunk():
    fake = MarkEvery()
    text = "我是学生我喜欢学习"
    punctuate_timed(text, _ts(len(text)), fake, CFG)
    assert fake.calls == [text]


def test_latin_words_keep_their_space_and_a_changed_chunk_is_not_used():
    class Rewrites:
        def punctuate(self, text): return "不一样。"
    text = "我用 PPT 做 报告"
    out = punctuate_timed(text, _ts(6), MarkEvery(), CFG)
    assert "PPT" in out and _speech(out) == "我用PPT做报告"
    assert _speech(punctuate_timed("我是学生", _ts(4), Rewrites(), CFG)) == "我是学生"


def _punctuator(tmp_path, sha="0" * 64):
    return SherpaPunctuator("m", "http://example.invalid/m.tar.bz2", sha, tmp_path)


def test_download_refuses_bad_checksum(monkeypatch, tmp_path):
    import urllib.request
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, *a, **k: io.BytesIO(b"not the model"))
    with pytest.raises(RuntimeError, match="checksum"):
        _punctuator(tmp_path)._model_path()
    assert not list((tmp_path / "m").rglob("*.onnx"))


def test_download_unpacks_after_a_good_checksum(monkeypatch, tmp_path):
    import hashlib
    import tarfile
    import urllib.request
    src = tmp_path / "src"
    (src / "m").mkdir(parents=True)
    (src / "m" / "model.int8.onnx").write_bytes(b"onnx")
    tgz = tmp_path / "m.tar.bz2"
    with tarfile.open(tgz, "w:bz2") as t:
        t.add(src / "m", arcname="m")
    data = tgz.read_bytes()
    monkeypatch.setattr(urllib.request, "urlopen", lambda url, *a, **k: io.BytesIO(data))
    p = _punctuator(tmp_path / "cache", hashlib.sha256(data).hexdigest())
    path = p._model_path()
    assert path.name == "model.int8.onnx" and path.read_bytes() == b"onnx"
    assert p.model_file == path                      # what prepare lists in its manifest
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: pytest.fail("downloaded twice"))
    assert p._model_path() == path


def test_models_cache_dir_from_env(monkeypatch, tmp_path):
    from shadow.ingest.punct import models_cache_dir
    monkeypatch.setenv("SHADOW_MODELS_DIR", str(tmp_path))
    assert models_cache_dir() == tmp_path
    monkeypatch.delenv("SHADOW_MODELS_DIR")
    assert models_cache_dir().parts[-2:] == ("shadow-speech", "models")


def test_load_builds_the_sherpa_model_once(monkeypatch, tmp_path):
    seen = []

    class Cfg:
        def __init__(self, **kw): seen.append(kw)

    class Punct:
        def __init__(self, cfg): pass
        def add_punctuation(self, t): return t + "。"

    fake = types.SimpleNamespace(
        OfflinePunctuationConfig=Cfg, OfflinePunctuationModelConfig=lambda **kw: kw, OfflinePunctuation=Punct)
    monkeypatch.setitem(sys.modules, "sherpa_onnx", fake)
    p = _punctuator(tmp_path)
    monkeypatch.setattr(p, "_model_path", lambda: tmp_path / "model.int8.onnx")
    assert p.punctuate("你好") == "你好。" and p.punctuate("再见") == "再见。"
    assert len(seen) == 1 and seen[0]["model"]["ct_transformer"].endswith("model.int8.onnx")


def _tarball(tmp_path):
    import hashlib
    import tarfile
    src = tmp_path / "src"
    (src / "m").mkdir(parents=True)
    (src / "m" / "model.int8.onnx").write_bytes(b"onnx")
    tgz = tmp_path / "m.tar.bz2"
    with tarfile.open(tgz, "w:bz2") as t:
        t.add(src / "m", arcname="m")
    data = tgz.read_bytes()
    return data, hashlib.sha256(data).hexdigest()


def test_a_partial_leftover_without_the_marker_is_downloaded_afresh(monkeypatch, tmp_path):
    import urllib.request
    data, sha = _tarball(tmp_path)
    cache = tmp_path / "cache"
    (cache / "m" / "m").mkdir(parents=True)
    (cache / "m" / "m" / "model.int8.onnx").write_bytes(b"trunc")        # an old partial unpack: no .complete
    (cache / "m.tmp-dead").mkdir()
    calls = []

    def fake(url, *a, **k):
        calls.append(url)
        return io.BytesIO(data)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    path = _punctuator(cache, sha)._model_path()
    assert calls and path.read_bytes() == b"onnx"
    assert (cache / "m" / ".complete").exists()
    assert sorted(p.name for p in cache.iterdir()) == ["m", "m.tmp-dead"]      # our temp files are gone


def test_a_failed_download_leaves_no_marker_and_no_temp_files(monkeypatch, tmp_path):
    import urllib.request

    class Dies(io.BytesIO):
        def read(self, n=-1):
            raise OSError("connection reset")
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: Dies())
    cache = tmp_path / "cache"
    with pytest.raises(OSError):
        _punctuator(cache)._model_path()
    assert list(cache.iterdir()) == []


def test_two_concurrent_first_uses_both_get_a_whole_model(monkeypatch, tmp_path):
    import threading
    import urllib.request
    data, sha = _tarball(tmp_path)
    barrier = threading.Barrier(2)

    def fake(url, *a, **k):
        barrier.wait(timeout=10)              # both are downloading at once
        return io.BytesIO(data)
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    cache = tmp_path / "cache"
    got, errs = [], []

    def run():
        try:
            got.append(_punctuator(cache, sha)._model_path().read_bytes())
        except Exception as e:                # noqa: BLE001
            errs.append(e)
    ts = [threading.Thread(target=run) for _ in range(2)]
    [t.start() for t in ts]
    [t.join(30) for t in ts]
    assert not errs and got == [b"onnx", b"onnx"]
    assert sorted(p.name for p in cache.iterdir()) == ["m"]


@pytest.mark.models
def test_sherpa_real_model_punctuates(tmp_path):
    from shadow.config import ModelsCfg
    m = ModelsCfg()
    p = SherpaPunctuator(m.punctuation_model, m.punctuation_url, m.punctuation_sha256, tmp_path)
    out = p.punctuate("我是学生我喜欢学习中文你呢")
    assert any(is_punct(ch) for ch in out) and _speech(out) == "我是学生我喜欢学习中文你呢"


def test_a_rejected_chunk_is_split_at_pauses_not_left_as_one_sentence():
    class Rewrites:
        def punctuate(self, text: str) -> str:
            return text + "额"                     # changes the speech: rejected

    text = "我是学生我爱中文你好吗再见谢谢你"
    out = punctuate_timed(text, _ts(len(text), {7: 900}), Rewrites(), CFG)   # a long pause after the 8th char
    assert _speech(out) == text
    assert out.count("。") == 2 and out.endswith("。")
    assert out.index("。") == 8
