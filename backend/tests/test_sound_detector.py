from __future__ import annotations
from shadow.scoring.sounds.charctc import group_matrix


def test_group_matrix_pools_heteronyms():
    vocab = {"<pad>": 0, "吃": 1, "行": 2, "a": 3}
    M = group_matrix(vocab, 4, 0, ["chi", "hang", "xing"])
    assert M.shape == (4, 4)
    assert M[0, 0] == 1
    assert M[1, 1] == 1
    assert M[2, 2] == M[2, 3] == 1
    assert M[3].sum() == 0


# --- the per-take detector, over fake models whose log-prob matrices spell a chosen syllable sequence ---------------

import numpy as np
import torch

from shadow.config import SoundsCfg
from shadow.scoring.sounds.detector import FakeSounds, SoundDetector

FRAME_S = 0.02
TAKE, REF = 1.0, 2.0                       # the fakes tell the take from the reference by the waveform's value
LETTERS = {c: i + 1 for i, c in enumerate("abcdefghijklmnopqrstuvwxyz")}     # 0 = blank


def _spell(tokens: list[list[int]], C: int) -> tuple[torch.Tensor, list[tuple[float, float]]]:
    """Frame log-probs: a blank, then each syllable's tokens two frames each and a blank; 0.9 on the intended class.
    Also returns each syllable's time window."""
    cls, wins = [0], []
    for t in tokens:
        a = len(cls)
        for x in t:
            cls += [x, x]
        wins.append((a * FRAME_S, len(cls) * FRAME_S))
        cls.append(0)
    p = torch.full((len(cls), C), 0.1 / (C - 1))
    for f, c in enumerate(cls):
        p[f, c] = 0.9
    return p.log(), wins


class FakeLetters:
    blank = 0

    def __init__(self, spoken: dict[float, list[str]]):
        self.spoken = spoken
        self.calls = 0

    def letter_ids(self, s: str) -> list[int]:
        return [LETTERS[c] for c in s.replace("v", "u") if c in LETTERS] or [LETTERS["a"]]

    def emissions(self, wav, sr):
        self.calls += 1
        lp, _ = _spell([self.letter_ids(s) for s in self.spoken[float(wav[0])]], len(LETTERS) + 1)
        return lp, FRAME_S


class FakeChars:
    blank = 0
    SID = {"ta": 1, "chi": 2, "ci": 3, "er": 4, "ding": 5, "a": 6}           # "din" has no characters: no sid
    COL = {**SID, "din": 7}                                                   # ...but it has a column

    def __init__(self, spoken: dict[float, list[str]]):
        self.spoken = spoken
        self.calls: list[float] = []

    def sid(self, s: str) -> int | None:
        return self.SID.get(s)

    def column(self, s: str) -> int | None:
        return self.COL.get(s)

    def group_logp(self, wav, sr):
        self.calls.append(float(wav[0]))
        with torch.inference_mode():       # the real model hands back inference-mode tensors
            lp, _ = _spell([[self.COL[s]] for s in self.spoken[float(wav[0])]], len(self.COL) + 1)
            return lp.clone()


def _syl(p: str, tone: int) -> dict:
    return {"ch": "x", "pinyin_toneless": p, "tone": tone}


def _detector(take: list[str], ref: list[str]):
    spoken = {TAKE: take, REF: ref}
    letters, chars = FakeLetters(spoken), FakeChars(spoken)
    _, wins = _spell([letters.letter_ids(s) for s in take], len(LETTERS) + 1)
    return SoundDetector(letters, chars, SoundsCfg()), letters, chars, wins


def _check(det, wins, syllables, statuses=None, ref_key="clip|text"):
    return det.check(take=np.full(1600, TAKE, np.float32), sr=16000, usr_win=wins,
                     ref_wav=np.full(1600, REF, np.float32), ref_sr=16000, ref_key=ref_key,
                     syllables=syllables, statuses=statuses or ["good"] * len(syllables))


def test_check_marks_a_slip_and_names_what_was_heard():
    det, _, _, wins = _detector(["ta", "ci"], ["ta", "chi"])
    out = _check(det, wins, [_syl("ta", 1), _syl("chi", 1)])
    assert out[0] is None                  # ta has no contrast partner
    assert out[1]["status"] == "slip" and out[1]["rule"] == "fused"
    assert out[1]["heard"] == "ci" and out[1]["heard_pinyin"] == "cī"
    assert out[1]["z"] > SoundsCfg().fused_threshold


def test_check_ok_when_take_matches_reference():
    det, _, _, wins = _detector(["ta", "chi"], ["ta", "chi"])
    out = _check(det, wins, [_syl("ta", 1), _syl("chi", 1)])
    assert out[1]["status"] == "ok"
    assert out[1]["heard"] is None and out[1]["heard_pinyin"] is None


def test_check_skips_unjudgeable_syllables():
    take = ["er", "chi", "a", "ding"]
    det, letters, chars, wins = _detector(take, take)
    out = _check(det, wins, [_syl("er", 2), _syl("chi", 1), _syl("A", -1), _syl("ding", 1)],
                 statuses=["good", "missing", "good", "good"])
    # er: no partner; chi: missing; A: not a hanzi; ding: only din, which model B cannot say
    assert out == [None, None, None, None]
    assert letters.calls == 0 and chars.calls == []      # nothing checkable: no model runs


def test_letter_emissions_of_the_take_from_its_own_model_are_reused():
    from shadow.ingest.align import LetterEmissions
    det, letters, _, wins = _detector(["ta", "ci"], ["ta", "chi"])
    syls = [_syl("ta", 1), _syl("chi", 1)]
    computed = _check(det, wins, syls)
    assert letters.calls == 1
    em = LetterEmissions(*letters.emissions(np.full(1600, TAKE, np.float32), 16000), letters)
    letters.calls = 0
    reused = det.check(take=np.full(1600, TAKE, np.float32), sr=16000, usr_win=wins,
                       ref_wav=np.full(1600, REF, np.float32), ref_sr=16000, ref_key="clip|text",
                       syllables=syls, statuses=["good", "good"], letter_emissions=em)
    assert reused == computed and letters.calls == 0


def test_letter_emissions_from_another_model_are_not_trusted():
    from shadow.ingest.align import LetterEmissions
    det, letters, _, wins = _detector(["ta", "ci"], ["ta", "chi"])
    syls = [_syl("ta", 1), _syl("chi", 1)]
    other = LetterEmissions(*letters.emissions(np.full(1600, REF, np.float32), 16000), object())   # wrong take, too
    letters.calls = 0
    out = det.check(take=np.full(1600, TAKE, np.float32), sr=16000, usr_win=wins,
                    ref_wav=np.full(1600, REF, np.float32), ref_sr=16000, ref_key="clip|text",
                    syllables=syls, statuses=["good", "good"], letter_emissions=other)
    assert letters.calls == 1 and out == _check(det, wins, syls)


def test_reference_gops_are_cached():
    det, _, chars, wins = _detector(["ta", "ci"], ["ta", "chi"])
    syls = [_syl("ta", 1), _syl("chi", 1)]
    a = _check(det, wins, syls)
    b = _check(det, wins, syls)
    assert a == b
    assert chars.calls.count(REF) == 1 and chars.calls.count(TAKE) == 2
    _check(det, wins, syls, ref_key="other|text")
    assert chars.calls.count(REF) == 2


def test_reference_cache_keeps_the_last_64():
    det, _, chars, wins = _detector(["ta", "chi"], ["ta", "chi"])
    syls = [_syl("ta", 1), _syl("chi", 1)]
    for k in range(65):
        _check(det, wins, syls, ref_key=f"clip{k}")
    _check(det, wins, syls, ref_key="clip64")
    assert chars.calls.count(REF) == 65
    _check(det, wins, syls, ref_key="clip0")
    assert chars.calls.count(REF) == 66


def test_fake_sounds_returns_or_raises():
    syls = [_syl("chi", 1)]
    kw = dict(take=np.zeros(1), sr=16000, usr_win=[(0.0, 0.1)], ref_wav=np.zeros(1), ref_sr=16000, ref_key="k",
              syllables=syls, statuses=["good"])
    assert FakeSounds().check(**kw) == [None]
    r = [{"status": "ok", "heard": None, "heard_pinyin": None, "z": 0.0, "rule": "fused"}]
    assert FakeSounds(r).check(**kw) == r
    import pytest
    with pytest.raises(RuntimeError):
        FakeSounds(error=True).check(**kw)


def test_b_sequence_keeps_the_column_of_a_syllable_without_characters(monkeypatch):
    # spike: SID covers every inventory syllable, so "din" (no characters) is its own column, not blank; "xyz" is
    # outside the inventory and becomes blank
    import shadow.scoring.sounds.detector as detector
    seqs = []
    real = detector.utt_gops

    def spy(logp, blank, seq, alts):
        seqs.append(seq)
        return real(logp, blank, seq, alts)

    monkeypatch.setattr(detector, "utt_gops", spy)
    det, _, _, wins = _detector(["din", "chi", "a"], ["din", "chi", "a"])
    out = _check(det, wins, [_syl("din", 1), _syl("chi", 1), _syl("xyz", 1)])
    assert seqs == [[[7], [2], [0]]] * 2               # reference and take
    assert out[1]["status"] == "ok" and out[2] is None


def test_charctc_column_covers_the_inventory_without_loading():
    from shadow.scoring.sounds.charctc import CharCtc
    from shadow.scoring.sounds.contrasts import inventory
    m = CharCtc("unused", "unused", "cpu")
    inv = sorted(inventory())
    assert m.column("din") == inv.index("din") + 1
    assert m.column(inv[0]) == 1 and m.column(inv[-1]) == len(inv)
    assert m.column("xyz") is None
    assert m._model is None


def test_sound_ref_key_changes_when_the_clip_is_rebuilt(tmp_path):
    # a rebuilt clip at the same path must not reuse the cached reference GOPs of the old one
    import os
    from shadow.scoring.reference import sound_ref_key
    from shadow.store.models import Segment
    clip = tmp_path / "c.wav"
    seg = Segment(lesson_id=1, idx=0, start_s=0, end_s=1, text="吃", clip_wav_path=str(clip))
    syls = [{"pinyin_toneless": "chi"}]
    assert sound_ref_key(seg, syls) == f"{clip}|吃|chi|0"                  # missing clip: 0
    clip.write_bytes(b"x"); os.utime(clip, ns=(1, 1_000))
    first = sound_ref_key(seg, syls)
    assert first == f"{clip}|吃|chi|1000"
    os.utime(clip, ns=(1, 2_000))
    assert sound_ref_key(seg, syls) != first
