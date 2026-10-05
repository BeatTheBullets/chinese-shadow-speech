from shadow.ingest.text import to_simplified, strip_punct, parse_subtitles, strip_html, is_punct

SRT = """1
00:00:01,000 --> 00:00:02,500
你好，世界。

2
00:00:03,000 --> 00:00:04,000
<i>再見</i>
"""

VTT = """WEBVTT

00:01.000 --> 00:02.500
你好

00:03.000 --> 00:04.000
再见
"""


def test_simplified():
    assert to_simplified("再見世界") == "再见世界"


def test_punct():
    assert strip_punct("你好，世界。！？") == "你好世界"
    assert is_punct("，") and not is_punct("你")


def test_strip_html():
    assert strip_html('<div class="x">你好<br>世界</div>&nbsp;') == "你好 世界"


def test_parse_srt_simplifies_and_strips_tags():
    cues = parse_subtitles(SRT, "a.srt")
    assert cues[0].start == 1.0 and cues[0].end == 2.5 and cues[0].text == "你好，世界。"
    assert cues[1].text == "再见"


def test_parse_vtt():
    cues = parse_subtitles(VTT, "a.vtt")
    assert [c.text for c in cues] == ["你好", "再见"]
    assert cues[1].start == 3.0


def test_parse_plain():
    cues = parse_subtitles("第一句。\n\n第二句。\n", "a.txt")
    assert [c.text for c in cues] == ["第一句。", "第二句。"]
    assert cues[0].start == -1


def test_curly_quotes_in_punct():
    assert is_punct("“") and is_punct("”") and is_punct("‘") and is_punct("’")
    assert strip_punct("“你好”") == "你好"
