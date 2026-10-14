"""Pitch-altered training copies (Phase 2 spec §10.1): a native recording with each syllable's window given another
tone's contour, so the classifier must hear the pitch rather than recognise the character. Training only."""
from __future__ import annotations
import numpy as np
from shadow.scoring.pitch import Baseline

LEVEL = 0.6                              # one Chao level, in units of the speaker's spread (semitones)
TEMPLATES = {1: [5, 5, 5, 5, 5], 2: [3, 2.7, 3, 4, 5], 3: [2, 1.3, 1, 1, None], 4: [5, 4.5, 3.5, 2, 1]}
FRACS = [0.05, 0.27, 0.5, 0.73, 0.95]    # where in the window each template point sits
CHOICES = (1, 2, 3, 4, "flat")


def contour_units(choice: int | str, rng: np.random.Generator) -> np.ndarray:
    """Five points in spread units around the speaker's median; each syllable's range and offset jittered so the
    templates do not become a fingerprint. "flat" is exactly the median; None in a template is a random 1–3 tail."""
    if choice == "flat":
        return np.zeros(len(FRACS))
    levels = np.array([x if x is not None else rng.uniform(1.0, 3.0) for x in TEMPLATES[choice]])
    return (levels - 3) * LEVEL * rng.uniform(0.7, 1.3) + rng.uniform(-0.3, 0.3)


def resynth(wav: np.ndarray, sr: int, wins: list[tuple[float, float]], units: list[np.ndarray] | None,
            base: Baseline, floor: float, ceiling: float) -> np.ndarray:
    """PSOLA (Praat Manipulation → new PitchTier → overlap-add) with each window's contour replaced by its units."""
    if units is None:
        return wav
    import parselmouth
    from parselmouth.praat import call
    snd = parselmouth.Sound(np.asarray(wav, np.float64), sampling_frequency=sr)
    man = call(snd, "To Manipulation", 0.01, floor, ceiling)
    tier = call("Create PitchTier", "imposed", 0, snd.duration)
    for (a, b), u in zip(wins, units):
        for f, v in zip(FRACS, u):
            call(tier, "Add point", a + f * (b - a), base.hz * 2 ** (v * base.spread_st / 12))
    call([tier, man], "Replace pitch tier")
    return call(man, "Get resynthesis (overlap-add)").values[0].astype(np.float32)


def alter_choices(tones: list[int | None], rng: np.random.Generator) -> tuple[list, list[int]]:
    """Per syllable a contour other than its own tone; its label is the imposed tone (flat sounds like tone 1), or
    −1 for a neutral or unlabelled syllable, whose altered row says nothing reliable."""
    choices = []
    for t in tones:
        opts = [c for c in CHOICES if c != t]
        choices.append(opts[int(rng.integers(len(opts)))])
    labels = [(1 if c == "flat" else c) if t in (1, 2, 3, 4) else -1 for c, t in zip(choices, tones)]
    return choices, labels
