import pytest
from shadow.ingest import enrich
from shadow.ingest.enrich import words_for, syllables_for
from shadow.ingest.text import is_punct
from shadow.store.files import FileLayout
from tests.helpers import make_tone_wav


def test_words_for_groups_by_jieba_and_marks_ranges():
    w = words_for("我今天不去。")
    assert w[0]["word"] == "我" and w[0]["char_from"] == 0 and w[0]["char_to"] == 0
    assert w[1]["word"] == "今天" and w[1]["pinyin"] == "jīntiān" and w[1]["tones"] == [1, 1]
    assert w[1]["syllables"][1] == {"ch": "天", "pinyin": "tiān", "pinyin_toneless": "tian", "tone": 1}
    assert all(x["word"] != "。" for x in w)


def test_tone_sandhi_and_neutral():
    s = syllables_for("你好们")
    assert [x["tone"] for x in s][:2] == [2, 3]            # 3+3 → 2+3
    assert s[2]["tone"] == 0 and s[2]["pinyin_toneless"] == "men"
    assert s[0]["pinyin_toneless"] == "ni"


@pytest.mark.parametrize("text", [
    "我2024年用AI学中文。",
    "3.5%的人说：“OK！”",
    "我们 是 C-3PO 的朋友，哈哈……",
    "２０２４年",
])
def test_one_syllable_per_speech_char_with_non_hanzi_tone_minus_one(text):
    chars = [c for c in text if not is_punct(c)]
    syl = syllables_for(text)
    assert [s["ch"] for s in syl] == chars
    for s in syl:
        if not ("一" <= s["ch"] <= "鿿"):
            assert s["tone"] == -1 and s["pinyin"] == s["ch"]
        else:
            assert s["tone"] in (0, 1, 2, 3, 4)


def test_mixed_sentence_values():
    syl = syllables_for("我2024年用AI学中文。")
    assert [s["ch"] for s in syl] == list("我2024年用AI学中文")
    assert [s["tone"] for s in syl] == [3, -1, -1, -1, -1, 2, 4, -1, -1, 2, 1, 2]
    assert syl[1] == {"ch": "2", "pinyin": "2", "pinyin_toneless": "2", "tone": -1}
    assert syl[5]["pinyin"] == "nián"


def test_words_for_per_char_entries_cover_speech_chars_in_order():
    text = "我2024年用AI学中文。"
    ws = words_for(text)
    chars = [c for c in text if not is_punct(c)]
    assert [s["ch"] for w in ws for s in w["syllables"]] == chars
    for w in ws:
        assert len(w["syllables"]) == len(w["tones"])
        assert w["tones"] == [s["tone"] for s in w["syllables"]]
        assert w["pinyin"] == "".join(s["pinyin"] for s in w["syllables"])
        assert text[w["char_from"]:w["char_to"] + 1] == w["word"]


def test_punct_inside_token_is_skipped_but_range_kept():
    ws = words_for("3.5")
    assert len(ws) == 1 and ws[0]["word"] == "3.5" and (ws[0]["char_from"], ws[0]["char_to"]) == (0, 2)
    assert [s["ch"] for s in ws[0]["syllables"]] == ["3", "5"]


def test_syllables_for_raises_on_count_violation(monkeypatch):
    monkeypatch.setattr(enrich, "words_for", lambda text: [{"syllables": []}])
    with pytest.raises(ValueError):
        syllables_for("你好")


def test_make_clips_writes_wav_and_opus(tmp_path):
    src = make_tone_wav(tmp_path / "src.wav", 3.0)
    wav, opus = enrich.make_clips(FileLayout(tmp_path), 7, 2, src, 0.5, 2.0)
    assert wav == tmp_path / "lessons/7/clips/2.wav" and opus == tmp_path / "lessons/7/clips/2.opus"
    assert wav.stat().st_size > 0 and opus.stat().st_size > 0
