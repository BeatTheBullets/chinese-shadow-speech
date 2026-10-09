from shadow.scoring.corpus import parse_label, read_split, realise


def test_parse_label():
    assert parse_label("hao3") == ("hao", 3)
    assert parse_label("ma5") == ("ma", 0)
    assert parse_label("lv4") == ("lv", 4)
    assert parse_label("er2r") is None and parse_label("%") is None


def test_read_split_and_realise(tmp_path):
    split = tmp_path / "train"
    split.mkdir()
    (split / "content.txt").write_text(
        "SSB00050001.wav\t你 ni3 好 hao3 吗 ma5\n"
        "SSB00050002.wav\t一 yi1 个 ge4 儿 er2r\n"
        "broken line\n", encoding="utf-8")
    utts = read_split(split)
    assert len(utts) == 2
    u = utts[0]
    assert u.speaker == "SSB0005" and u.wav == split / "wav" / "SSB0005" / "SSB00050001.wav"
    assert u.chars == ["你", "好", "吗"] and u.tones == [3, 3, 0] and u.toneless == ["ni", "hao", "ma"]
    assert realise(u) == [2, 3, 0]                              # 3-3 sandhi
    assert realise(utts[1])[:2] == [2, 4] and realise(utts[1])[2] is None   # 一 before tone 4; unlabelled stays None
