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


def test_cjk_brackets_are_punct():
    assert all(is_punct(c) for c in "「」『』《》〈〉【】")


# yt-dlp auto-captions: each line is repeated as the first line of the next cue, with a 10 ms single-line cue
# in between; cue text contains whitespace-only lines and inline word timestamps.
ROLLING_VTT = """WEBVTT
Kind: captions
Language: zh

00:00:00.000 --> 00:00:02.000 align:start position:0%
 
我今天<00:00:00.500><c>想跟你们</c>

00:00:02.000 --> 00:00:02.010 align:start position:0%
我今天想跟你们
 

00:00:02.010 --> 00:00:04.000 align:start position:0%
我今天想跟你们
聊一聊<00:00:02.500><c>學中文</c>

00:00:04.000 --> 00:00:04.010 align:start position:0%
聊一聊学中文
 

00:00:04.010 --> 00:00:06.000 align:start position:0%
聊一聊学中文
的方法
"""


def test_parse_rolling_vtt_keeps_each_line_once():
    cues = parse_subtitles(ROLLING_VTT, "auto.zh.vtt")
    assert [c.text for c in cues] == ["我今天想跟你们", "聊一聊学中文", "的方法"]
    assert [c.start for c in cues] == [0.0, 2.01, 4.01]


def test_parse_non_rolling_subtitles_keep_repeated_and_multi_line_cues():
    srt = ("1\n00:00:01,000 --> 00:00:02,000\n对。\n\n2\n00:00:02,000 --> 00:00:03,000\n对。\n\n"
           "3\n00:00:03,000 --> 00:00:04,000\n你好\n世界\n\n4\n00:00:04,000 --> 00:00:05,000\n再见\n朋友\n")
    assert [c.text for c in parse_subtitles(srt, "a.srt")] == ["对。", "对。", "你好 世界", "再见 朋友"]
    vtt = "WEBVTT\n\n00:01.000 --> 00:02.000\n对\n\n00:02.000 --> 00:03.000\n对\n"
    assert [c.text for c in parse_subtitles(vtt, "a.vtt")] == ["对", "对"]
