"""The tone classifier and the per-syllable verdict (Phase 2 spec §3)."""
from __future__ import annotations
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
import numpy as np
from shadow.config import ScoringCfg
from shadow.scoring.features import FEATURE_VERSION, dtw_distance

log = logging.getLogger(__name__)
TONES = (0, 1, 2, 3, 4)                  # 0 = neutral
MODELS_DIR = Path(__file__).parent / "models"


class ToneModel(Protocol):
    version: str
    dtw_norm: float
    meta: dict

    def proba(self, X: np.ndarray) -> np.ndarray: ...


class FakeToneModel:
    """Tests: always hears `tone` with probability `p`, the rest spread evenly."""
    def __init__(self, tone: int = 1, p: float = 0.9, dtw_norm: float = 1.0):
        self.tone, self.p, self.dtw_norm, self.version = tone, p, dtw_norm, "fake"
        self.meta = {"version": "fake", "accuracy": None}

    def proba(self, X: np.ndarray) -> np.ndarray:
        row = np.full(len(TONES), (1 - self.p) / (len(TONES) - 1))
        row[TONES.index(self.tone)] = self.p
        return np.tile(row, (len(X), 1))


class SklearnToneModel:
    def __init__(self, clf, meta: dict):
        self.clf, self.meta = clf, meta
        self.version, self.dtw_norm = str(meta["version"]), float(meta["dtw_norm"])
        classes = [int(c) for c in clf.classes_]
        self._cols = [classes.index(t) for t in TONES]

    def proba(self, X: np.ndarray) -> np.ndarray:
        return self.clf.predict_proba(X)[:, self._cols]


def load_tone_model(name: str, models_dir: Path = MODELS_DIR) -> ToneModel | None:
    """The shipped model, or None (scores then carry `no_tone_model`) when it is missing, unreadable or built for
    other features. Never raises: build_deps loads it at start-up, and a bad file must not stop the server."""
    meta_p, model_p = models_dir / f"{name}.json", models_dir / f"{name}.joblib"
    if not (meta_p.exists() and model_p.exists()):
        log.warning("tone model %s not found in %s", name, models_dir)
        return None
    try:
        meta = json.loads(meta_p.read_text())
        if meta.get("feature_version") != FEATURE_VERSION:
            log.warning("tone model %s has feature version %s, the app %s", name, meta.get("feature_version"), FEATURE_VERSION)
            return None
        import joblib
        return SklearnToneModel(joblib.load(model_p), meta)
    except Exception:
        log.exception("tone model %s in %s could not be loaded", name, models_dir)
        return None


def target_tone(ref_p: np.ndarray | None, canonical: int, min_conf: float) -> int:
    """The tone the speaker produced when the model is sure of it, else the dictionary tone with sandhi."""
    if ref_p is not None and float(ref_p.max()) >= min_conf:
        return TONES[int(ref_p.argmax())]
    return canonical


def contour_similarity(ref: np.ndarray, usr: np.ndarray, band: int, norm: float) -> float:
    return 1.0 - min(max(dtw_distance(ref, usr, band) / norm, 0.0), 1.0)


@dataclass
class Verdict:
    status: str                          # ok | close | wrong
    tone_score: float
    p_target: float
    contour: float | None
    heard: int


def judge(p_usr: np.ndarray, target: int, contour: float | None, cfg: ScoringCfg) -> Verdict:
    p_target = float(p_usr[TONES.index(target)])
    heard = TONES[int(p_usr.argmax())]
    score = p_target if target == 0 or contour is None else cfg.tone_weight * p_target + (1 - cfg.tone_weight) * contour
    if heard != target and float(p_usr.max()) - p_target >= cfg.wrong_margin:
        status = "wrong"
    elif heard == target and score >= cfg.green_at:
        status = "ok"
    else:
        status = "close"
    return Verdict(status, score, p_target, contour, heard)


def sentence_overall(items: list[tuple[str, float | None]]) -> float | None:
    """Mean tone_score over the syllables that are not unvoiced, a missing one counting 0 (spec §3)."""
    vals = [0.0 if status == "missing" else s for status, s in items if status != "unvoiced"]
    vals = [v for v in vals if v is not None]
    return sum(vals) / len(vals) if vals else None
