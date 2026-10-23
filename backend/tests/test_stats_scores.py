from datetime import datetime, timedelta, timezone

import pytest

from shadow.scoring.sounds.contrasts import DIRECTIONS, HARD_DIRECTIONS
from shadow.stats.scores import (Score, SylRow, char_right, character_stats, characters_score, rank_sentences,
                                 score_set, sound_directions, sounds_score, tone_groups, tone_value, tones_score,
                                 weakest_sounds, weakest_tones)

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)


def row(ch="好", py="hao", tone=3, prev=None, score=0.8, status="ok", sound=None, heard=None, days_ago=1, attempt=1,
        idx=0) -> SylRow:
    return SylRow(ch, py, tone, prev, score, status, sound, heard, NOW - timedelta(days=days_ago), attempt, idx)


def test_hard_directions():
    assert HARD_DIRECTIONS <= set(DIRECTIONS) and len(HARD_DIRECTIONS) == 18
    assert not HARD_DIRECTIONS & {"f>h", "h>f", "ai>ei", "ei>ai", "ao>ou", "ou>ao"}


def test_tone_value_rules():
    assert tone_value(row(status="missing", score=None)) == 0.0
    assert tone_value(row(status="unvoiced")) is None
    assert tone_value(row(score=0.8)) == 0.8


def test_tones_score_leaves_neutral_out_and_counts_missing_as_zero():
    rows = ([row(score=1.0)] * 20 + [row(status="missing", score=None)] * 10 + [row(tone=0, score=0.0)] * 5
            + [row(status="unvoiced")] * 5)
    assert tones_score(rows) == Score(20 / 30, 30)


def test_scores_need_enough_units():
    assert tones_score([row()] * 29) == Score(None, 29)
    assert sounds_score([row(py="chi", sound="ok")] * 29) == Score(None, 29)


def test_char_right_rules():
    assert char_right(row(status="ok", sound=None)) is True
    assert char_right(row(status="ok", sound="slip", heard="hou")) is False
    assert char_right(row(status="close")) is False and char_right(row(status="missing", score=None)) is False
    assert char_right(row(status="unvoiced")) is None and char_right(row(tone=0)) is None
    assert char_right(row(ch="A")) is None


def test_characters_score_is_a_mean_over_characters():
    rows = [row(ch="的", py="de", tone=0)] * 50
    rows += [row(ch="飞", py="fei", tone=1)] * 80
    for c in "一二三四五六七八九":
        rows += [row(ch=c, tone=1)] + [row(ch=c, tone=1, status="wrong")] * 3
    rows += [row(ch="十", tone=2)] * 2
    assert characters_score(rows) == Score(pytest.approx((1 + 9 * 0.25) / 10), 10)
    assert characters_score(rows[:-2 - 4]).value is None


def test_sounds_score_hard_only():
    rows = ([row(py="chi", sound="ok")] * 20 + [row(py="chi", sound="slip", heard="ci")] * 10
            + [row(py="fan", sound="slip", heard="han")] * 5
            + [row(py="fan", sound="ok")] * 5 + [row(py="fu", sound="ok")] * 5
            + [row(py="chi", sound=None)] * 5)
    assert sounds_score(rows) == Score(pytest.approx(25 / 35), 35)


def test_character_stats_rows():
    rows = ([row(attempt=i, status="wrong") for i in range(10)]
            + [row(attempt=i, days_ago=0) for i in range(10, 20)])
    rows += [row(ch="十", tone=2)] * 2
    rows += [row(ch="一", py="yi", tone=1, status="wrong")] * 3
    stats = character_stats(rows)
    assert [s["ch"] for s in stats] == ["一", "好"]
    hao = stats[1]
    assert hao["trend"] == 1.0 and hao["sound_right"] is None and hao["pinyin"] == "hǎo" and hao["takes"] == 20
    assert hao["tone_right"] == 0.5 and stats[0]["trend"] is None


def test_tone_groups_and_weakest_tones():
    rows = [row(tone=1, prev=0, score=0.9)] * 8
    rows += [row(tone=0, prev=1, score=0.2)] * 8 + [row(tone=3, prev=2, score=0.5)] * 7
    tones, pairs = tone_groups(rows)
    assert {t["tone"] for t in tones} == {0, 1, 3}
    assert any(p["prev_tone"] == 0 and p["tone"] == 1 for p in pairs)
    weak = weakest_tones(rows)
    assert [(w["kind"], w["key"], w["label"]) for w in weak] == [("pair", "1-0", "1 → 0"), ("tone", "1", "Tone 1")]
    assert all(w["key"] != "0" for w in weak)
    assert all(w["key"] != "2-3" for w in weak)


def test_sound_directions_and_weakest_sounds():
    rows = [row(py="chi", sound="slip", heard="ci")] * 2 + [row(py="chi", sound="ok")] * 6
    rows += [row(py="fu", sound="ok")] * 8 + [row(py="fa", sound="slip", heard="ha")] * 8
    rows += [row(py="zhi", sound="ok")] * 7
    dirs = {d["key"]: d for d in sound_directions(rows)}
    assert dirs["ch>c"]["hard"] and dirs["ch>c"]["slips"] == 2 and dirs["ch>c"]["chances"] == 8
    assert not dirs["f>h"]["hard"]
    assert "zh>z" not in dirs
    assert [d["key"] for d in weakest_sounds(rows)] == ["ch>c"]
    assert weakest_sounds([row(py="chi", sound="ok")] * 8) == []


def test_score_set_splits_weeks():
    rows = [row(score=1.0, days_ago=2)] * 30 + [row(score=0.5, days_ago=10)] * 30
    s = score_set(rows, NOW)
    assert s["tones"] == {"value": 0.75, "last7": 1.0, "prev7": 0.5, "n": 60}
    assert s["characters"]["last7"] is None


def test_empty_rows():
    assert tones_score([]) == characters_score([]) == sounds_score([]) == Score(None, 0)
    assert character_stats([]) == [] and weakest_tones([]) == [] and sound_directions([]) == []
    assert weakest_sounds([]) == [] and rank_sentences([]) == [] and tone_groups([]) == ([], [])


def test_rank_sentences():
    out = rank_sentences([{"id": 1, "last": .5, "best": .55}, {"id": 2, "last": .80, "best": .95},
                          {"id": 3, "last": .3, "best": .31}, {"id": 4, "last": .6, "best": .9}])
    assert [r["id"] for r in out] == [4, 2, 3, 1]
    assert [r["regressed"] for r in out] == [True, True, False, False]
