from shadow.scoring.sounds.contrasts import (DIRECTIONS, b_silent, checkable_directions_of, direction, direction_label,
                                             directions_of, drill_label, heard_pinyin, inventory, partners)

def test_inventory_is_the_spike_list():
    inv = inventory()
    assert len(inv) == 552 and "nv" in inv and "chi" in inv and "din" in inv   # din: no characters in B (Task 5)

def test_partners_match_the_spike():
    assert partners("chi") == [("ci", "ch/c")]
    assert partners("zen") == [("zhen", "zh/z"), ("zeng", "n/ng"), ("zan", "vowel")]
    assert partners("sheng") == [("seng", "sh/s"), ("shen", "n/ng"), ("shang", "vowel")]
    assert partners("dou") == [("dao", "vowel"), ("duo", "vowel")]
    assert partners("nv") == [("nu", "ü/u")] and partners("yu") == [("wu", "ü/u")]
    assert partners("wo") == [] and partners("de") == [] and partners("er") == []
    assert partners("ding") == [("din", "n/ng")]

def test_direction():
    assert direction("chi", "ci") == "ch>c" and direction("zen", "zhen") == "z>zh"
    assert direction("ping", "pin") == "ng>n" and direction("jin", "jing") == "n>ng"
    assert direction("yu", "wu") == "ü>u" and direction("nu", "nv") == "u>ü"
    assert direction("dou", "duo") == "ou>uo" and direction("men", "man") == "en>an"
    assert direction("chi", "shi") is None
    assert set(DIRECTIONS) >= {d for s in inventory() for d in directions_of(s)}

def test_labels_and_heard_pinyin():
    assert direction_label("ch>c") == "ch said as c" and direction_label("ng>n") == "-ng said as -n"
    assert drill_label("ü>u") == "ü (not u)"
    assert heard_pinyin("ci", 1) == "cī" and heard_pinyin("nv", 3) == "nǚ" and heard_pinyin("de", 0) == "de"


def test_checkable_directions_skip_partners_without_characters():
    assert "din" in b_silent() and b_silent() <= inventory() and "ding" not in b_silent()
    assert directions_of("ding") == {"ng>n"} and checkable_directions_of("ding") == set()   # din: never checked
    assert "ng>n" in checkable_directions_of("ping") and checkable_directions_of("chi") == {"ch>c"}
