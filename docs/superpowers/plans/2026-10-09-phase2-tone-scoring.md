# Phase 2 — Tone Scoring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score every take per syllable for tone (classifier verdict + contour similarity against the reference, both on speaker-normalised pitch), show it in the feedback block, and fill the tone stats, using a tone model trained once on AISHELL-3 and shipped in the repo.

**Architecture:** Pure scoring functions in `backend/shadow/scoring/` (pitch, features, tone verdicts, gate, `score_take`) wrapped by `score_attempt`, which handles the DB: the reference pitch cache, the lesson baseline, the voice profile and the `SyllableScore` rows. An offline script trains a scikit-learn classifier on AISHELL-3 with the same feature code. The frontend reads the score JSON on the attempt (and on stored takes) to colour cells, draw pitch lines and fill the Stats page.

**Tech Stack:** Python 3.12, FastAPI, SQLModel/SQLite, praat-parselmouth, scikit-learn, joblib, torchaudio MMS_FA (existing); React 18, Vite 5, vitest 3, Tailwind (existing).

**Spec:** `docs/superpowers/specs/2026-10-09-phase2-tone-scoring-design.md` (read it first; main spec `docs/superpowers/specs/2026-10-03-shadowing-tool-design.md` §5 for the original score JSON).

## Global Constraints

- Tones are `1`–`4` and `0` for neutral everywhere; `-1` means a non-hanzi character (from `words_json`).
- Statuses: `ok | close | wrong | unvoiced | missing`; `suspect` is reserved for Phase 3.
- Config defaults (`[scoring]`): `tone_weight = 0.5`, `dtw_band = 4`, `f0_floor = 60`, `f0_ceiling = 500`, `normalise_span = true`, `min_voiced_frames = 4`, `min_duration_ratio = 0.4`, `green_at = 0.7`, `wrong_margin = 0.25`, `ref_confidence = 0.6`, `min_rms_dbfs = -45.0`, `min_align_conf = 0.2`, `max_clipped = 0.01`, `profile_seconds = 60.0`, `tone_model = "tone_v1"`. (`min_rms_dbfs` and `min_align_conf` are re-set from the user's takes in Task 15.)
- Pitch: parselmouth autocorrelation, 10 ms step; retry once at 40–600 Hz when under 50 % of frames are voiced.
- Syllable contour: trim 15 % at each end, 20 points; `FEATURE_VERSION = 1`.
- A take is always saved and replayable; scoring never raises out of `score_attempt`.
- `overall` may be `null` in any stored score JSON; every reader must allow it.
- Backend commands run from `backend/` with `~/.local/bin/uv run …`; never run `uv sync` without `--extra dev --extra models` (it would uninstall torch).
- The tone model files (`backend/shadow/scoring/models/tone_v1.joblib`, `tone_v1.json`) are committed; the corpus under `data/corpora/` is not (already gitignored via `data/`).
- Match the surrounding code: dense one-line docstrings that say *why*, `from __future__ import annotations`, no new abstractions beyond those named here.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

- **A stored take with `overall: null`** (gate failure, scoring error, no model): the lessons API's last/best (`_attempt_stats` takes `max()`), `/stats/sentences`, `/lessons/{id}/stats` and every frontend `Math.round(x * 100)` must skip it, not crash or show `NaN`. Tests: Task 9 step 1 (`test_null_overall_is_skipped_by_lessons_and_stats`), Task 13 step 1 (`an unscored take only counts`).
- **Sentences with non-hanzi characters** (digits, Latin letters: tone `-1`): scored as `unvoiced`, never a crash or a red cell. Test: Task 6 (`test_non_hanzi_syllable_is_unvoiced`).
- **Near-silent or tiny takes** (a 0.1 s click, silence): parselmouth raises on sounds shorter than a few pitch periods, so the gate must reject them before any pitch call. Test: Task 6 (`test_tiny_take_is_gated_before_pitch`).
- **Aligner output that does not fit** (wrong span count, zero-length learner spans): `align_failed` or `missing`, no exception. Tests: Task 6 (`test_span_count_mismatch_is_align_failed`, `test_zero_length_learner_span_is_missing`).
- **Scoring while an ingest job aligns** (one GPU aligner shared by two threads): calls are serialised. Test: Task 5 (`test_locked_aligner_serialises_calls`).

## File Structure

Backend (new):
- `backend/shadow/scoring/pitch.py` — `Pitch`, `track_pitch`, `trim_silence`, `Baseline`, `baseline_of`, `blend`, `normalise`.
- `backend/shadow/scoring/features.py` — `FEATURE_VERSION`, `SylPitch`, `syllable_pitch`, `feature_matrix`, `dtw_distance`.
- `backend/shadow/scoring/tone.py` — `TONES`, `ToneModel`, `FakeToneModel`, `SklearnToneModel`, `load_tone_model`, `target_tone`, `contour_similarity`, `judge`, `sentence_overall`.
- `backend/shadow/scoring/gate.py` — `level_dbfs`, `clipped_ratio`, `pre_gate`, `align_gate`.
- `backend/shadow/scoring/score.py` — `RefData`, `TakeResult`, `score_take`, `failed_result`.
- `backend/shadow/scoring/reference.py` — `reference_pitch`, `reference_spans`, `lesson_baseline`, `segment_syllables`.
- `backend/shadow/scoring/profile.py` — voice profile DB helpers.
- `backend/shadow/scoring/corpus.py` — AISHELL-3 reading and labels (training only).
- `backend/shadow/scoring/report.py` — rescore sanity report HTML.
- `backend/shadow/scoring/models/tone_v1.{joblib,json}` — the trained model (Task 9).
- `backend/shadow/api/voice.py` — `/voice-profile`.
- `backend/scripts/tone_model.py`, `backend/scripts/rescore.py`.
- Tests: `backend/tests/test_pitch.py`, `test_features.py`, `test_tone.py`, `test_gate.py`, `test_score.py`, `test_scoring_api.py`, `test_corpus.py`, `test_report.py`, `test_voice_api.py`.

Backend (modified): `pyproject.toml`, `uv.lock`, `config.toml`, `shadow/config.py`, `shadow/store/models.py`, `shadow/store/db.py`, `shadow/deps.py`, `shadow/ingest/align.py`, `shadow/scoring/__init__.py`, `shadow/api/attempts.py`, `shadow/api/lessons.py`, `shadow/api/stats.py`, `shadow/api/health.py`, `shadow/schemas.py`, `shadow/main.py`, `Makefile`, `tests/helpers.py`, existing tests that asserted `score_json is None`.

Frontend (new): `src/lib/score.ts`, `src/lib/pitch.ts`, `src/components/ScoreHeader.tsx`, `src/components/PitchLine.tsx`, `src/components/ToneMatrix.tsx`, `src/components/ToneTrend.tsx`, tests next to each.

Frontend (modified): `src/api/types.ts`, `src/api/client.ts`, `src/lib/cells.ts`, `src/components/CellRow.tsx`, `src/components/TwoTrack.tsx`, `src/index.css`, `src/store/practice.ts`, `src/pages/Practice.tsx`, `src/pages/useFlow.ts`, `src/pages/Stats.tsx`, `src/pages/Settings.tsx`.

Docs: `README.MD`, `docs/running.md`, `docs/phase2-acceptance.md` (new).

---

### Task 1: Dependencies, config keys, tables and in-place column migration

**Files:**
- Modify: `backend/pyproject.toml`, `backend/uv.lock`, `backend/shadow/config.py:32-41`, `config.toml` (`[scoring]`), `backend/shadow/store/models.py`, `backend/shadow/store/db.py`
- Test: `backend/tests/test_config.py`, `backend/tests/test_store.py`

**Interfaces:**
- Produces: `ScoringCfg` fields listed in Global Constraints; `SyllableScore.target_tone: int | None`, `SyllableScore.heard_tone: int | None`; `VoiceProfile(id, frames_json: list[float], baseline_hz: float | None, spread_st: float | None, voiced_s: float, updated_at: datetime)`; `init_db(engine)` now also adds missing nullable columns.

- [ ] **Step 1: Add the dependencies**

```bash
cd backend && ~/.local/bin/uv add --no-sync "praat-parselmouth>=0.4.5" "scikit-learn>=1.5" "joblib>=1.4"
~/.local/bin/uv sync --extra dev --extra models
~/.local/bin/uv run python -c "import parselmouth, sklearn, joblib; print(parselmouth.__version__, sklearn.__version__)"
```
Expected: two version numbers print. Then pin scikit-learn to the installed minor in `pyproject.toml` (model pickles are version-sensitive), e.g. `"scikit-learn==1.7.*"` with the minor that printed, and run `~/.local/bin/uv lock` and the same `uv sync` again.

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_config.py`:
```python
def test_phase2_scoring_defaults():
    from shadow.config import Settings
    s = Settings().scoring
    assert (s.green_at, s.wrong_margin, s.ref_confidence) == (0.7, 0.25, 0.6)
    assert (s.min_rms_dbfs, s.min_align_conf, s.max_clipped, s.profile_seconds) == (-45.0, 0.2, 0.01, 60.0)
    assert s.tone_model == "tone_v1"


def test_repo_config_toml_has_phase2_scoring_keys():
    from pathlib import Path
    from shadow.config import load_settings
    s = load_settings(Path(__file__).resolve().parents[2] / "config.toml")
    assert s.scoring.tone_model == "tone_v1" and s.scoring.green_at == 0.7
```

Append to `backend/tests/test_store.py`:
```python
def test_init_db_adds_missing_nullable_columns_in_place(tmp_path):
    from sqlalchemy import inspect, text
    from shadow.store.db import init_db, make_engine
    eng = make_engine(tmp_path)
    with eng.begin() as c:     # the Phase 1 shape of the table
        c.execute(text("CREATE TABLE syllablescore (id INTEGER PRIMARY KEY AUTOINCREMENT, attempt_id INTEGER NOT NULL, "
                       "segment_id INTEGER NOT NULL, idx INTEGER NOT NULL, ch VARCHAR NOT NULL, pinyin_toneless VARCHAR NOT NULL, "
                       "tone INTEGER NOT NULL, prev_tone INTEGER, tone_score FLOAT, seg_score FLOAT, status VARCHAR NOT NULL)"))
        c.execute(text("INSERT INTO syllablescore (attempt_id, segment_id, idx, ch, pinyin_toneless, tone, status) "
                       "VALUES (1, 1, 0, '我', 'wo', 3, 'ok')"))
    init_db(eng)
    init_db(eng)               # idempotent
    insp = inspect(eng)
    assert {"target_tone", "heard_tone"} <= {c["name"] for c in insp.get_columns("syllablescore")}
    assert "voiceprofile" in insp.get_table_names()
    with eng.connect() as c:
        assert c.execute(text("SELECT ch, target_tone FROM syllablescore")).all() == [("我", None)]
```

- [ ] **Step 3: Run them to verify they fail**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_config.py tests/test_store.py -q`
Expected: FAIL (`AttributeError: 'ScoringCfg' object has no attribute 'green_at'`, missing columns).

- [ ] **Step 4: Implement**

`backend/shadow/config.py` — replace `ScoringCfg` with:
```python
class ScoringCfg(BaseModel):
    tone_weight: float = 0.5          # share of the classifier's P(target) in tone_score; the rest is contour similarity
    dtw_band: int = 4
    f0_floor: int = 60
    f0_ceiling: int = 500
    normalise_span: bool = True
    min_voiced_frames: int = 4
    gop_margin: float = 2.0
    min_duration_ratio: float = 0.4
    green_at: float = 0.7             # Phase 2 spec §3: ok needs the target tone heard and tone_score ≥ this
    wrong_margin: float = 0.25        # wrong: another tone beats P(target) by at least this
    ref_confidence: float = 0.6       # the reference's own classification becomes the target from this probability
    min_rms_dbfs: float = -45.0       # gate (spec §1); re-set from the user's takes in the plan's Task 15
    min_align_conf: float = 0.2
    max_clipped: float = 0.01
    profile_seconds: float = 60.0     # voiced seconds before the voice profile alone sets the learner's baseline
    tone_model: str = "tone_v1"       # backend/shadow/scoring/models/<name>.{joblib,json}
```

`config.toml` — replace the `[scoring]` block with:
```toml
[scoring]
tone_weight = 0.5
dtw_band = 4
f0_floor = 60
f0_ceiling = 500
normalise_span = true
min_voiced_frames = 4
gop_margin = 2.0
min_duration_ratio = 0.4
green_at = 0.7
wrong_margin = 0.25
ref_confidence = 0.6
min_rms_dbfs = -45.0
min_align_conf = 0.2
max_clipped = 0.01
profile_seconds = 60.0
tone_model = "tone_v1"
```

`backend/shadow/store/models.py` — in `SyllableScore` replace the `tone`/`prev_tone` lines with:
```python
    tone: int                             # canonical tone from words_json (0 neutral, -1 non-hanzi)
    prev_tone: int | None = None          # the previous syllable's target tone (its canonical tone when unscored)
    target_tone: int | None = None        # the tone the speaker produced (Phase 2 spec §3)
    heard_tone: int | None = None         # the classifier's top tone on the learner's syllable
```
and append:
```python
class VoiceProfile(SQLModel, table=True):
    """The learner's pitch baseline (Phase 2 spec §2), one row per installation: the most recent voiced F0 frames
    and the median and interquartile range derived from them. `voiced_s` counts every voiced second ever added."""
    id: int | None = Field(default=None, primary_key=True)
    frames_json: list[float] = Field(default_factory=list, sa_column=Column(JSON))
    baseline_hz: float | None = None
    spread_st: float | None = None
    voiced_s: float = 0.0
    updated_at: datetime = Field(default_factory=now)
```

`backend/shadow/store/db.py` — replace the imports and `init_db` with:
```python
from pathlib import Path
from typing import Iterator
from fastapi import Request
from sqlalchemy import Engine, inspect, text
from sqlmodel import SQLModel, Session, create_engine
from shadow.store import models  # noqa: F401  (registers tables)
```
```python
def init_db(engine: Engine) -> None:
    SQLModel.metadata.create_all(engine)
    _add_missing_columns(engine)


def _add_missing_columns(engine: Engine) -> None:
    """create_all never alters an existing table: add the nullable columns newer models declare (Phase 2 spec §5.2)."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in SQLModel.metadata.sorted_tables:
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in have:
                    continue
                if not col.nullable:
                    raise RuntimeError(f"cannot add NOT NULL column {table.name}.{col.name} in place")
                conn.execute(text(f'ALTER TABLE "{table.name}" ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}'))
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && ~/.local/bin/uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/shadow/config.py config.toml backend/shadow/store/models.py backend/shadow/store/db.py backend/tests/test_config.py backend/tests/test_store.py
git commit -m "feat(backend): Phase 2 scoring config, voice profile table, in-place column migration"
```

---

### Task 2: Pitch, silence trim and baselines

**Files:**
- Create: `backend/shadow/scoring/pitch.py`
- Modify: `backend/tests/helpers.py` (synthetic voice)
- Test: `backend/tests/test_pitch.py`

**Interfaces:**
- Produces:
  - `STEP_S = 0.01`
  - `@dataclass Pitch(t0: float, f0: np.ndarray)` with `.times() -> np.ndarray`, `.voiced() -> np.ndarray` (f0 in Hz, `nan` unvoiced)
  - `track_pitch(wav: np.ndarray, sr: int, floor: float = 60, ceiling: float = 500) -> Pitch`
  - `trim_silence(wav: np.ndarray, sr: int, keep_s: float = 0.05, rel_db: float = -35.0) -> tuple[np.ndarray, float]`
  - `@dataclass Baseline(hz: float, spread_st: float)`; `baseline_of(f0: np.ndarray) -> Baseline | None`; `blend(profile: Baseline | None, take: Baseline | None, w_take: float) -> Baseline | None`; `normalise(f0: np.ndarray, base: Baseline, span: bool) -> np.ndarray`
  - test helper `voice(contours: list[tuple[float, float]], syl_s: float = 0.25, sr: int = 16000, lead_s: float = 0.0) -> np.ndarray`

- [ ] **Step 1: Add the synthetic voice helper**

Append to `backend/tests/helpers.py`:
```python
def voice(contours: list[tuple[float, float]], syl_s: float = 0.25, sr: int = 16000, lead_s: float = 0.0) -> np.ndarray:
    """A harmonic test 'voice': per syllable the pitch moves linearly from a to b Hz (continuous phase), with `lead_s`
    of silence on each side. Pitch trackers follow it like a sustained vowel."""
    f = np.concatenate([np.linspace(a, b, int(syl_s * sr), endpoint=False) for a, b in contours])
    phase = 2 * np.pi * np.cumsum(f) / sr
    x = sum(np.sin(k * phase) / k for k in range(1, 6)) * 0.2
    pad = np.zeros(int(lead_s * sr))
    return np.concatenate([pad, x, pad]).astype("float32")
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_pitch.py`:
```python
import numpy as np
import pytest
from shadow.scoring.pitch import Baseline, STEP_S, baseline_of, blend, normalise, track_pitch, trim_silence
from tests.helpers import voice

SR = 16000


def test_track_pitch_follows_a_steady_and_a_rising_voice():
    p = track_pitch(voice([(200, 200)], syl_s=1.0), SR)
    assert abs(np.nanmedian(p.f0) - 200) < 2
    assert np.mean(~np.isnan(p.f0)) > 0.8
    rise = track_pitch(voice([(150, 300)], syl_s=1.0), SR)
    v = rise.f0[~np.isnan(rise.f0)]
    assert v[-5:].mean() > v[:5].mean() + 100
    assert abs(rise.times()[1] - rise.times()[0] - STEP_S) < 1e-9


def test_track_pitch_marks_silence_unvoiced():
    p = track_pitch(np.zeros(SR, dtype="float32"), SR)
    assert np.isnan(p.f0).all() and len(p.voiced()) == 0


def test_trim_silence_cuts_both_ends_and_reports_the_offset():
    x = voice([(200, 200)], syl_s=0.5, lead_s=0.6)
    y, off = trim_silence(x, SR)
    assert 0.5 <= off <= 0.6
    assert 0.55 <= len(y) / SR <= 0.65


def test_trim_silence_leaves_silence_alone():
    x = np.zeros(SR // 2, dtype="float32")
    y, off = trim_silence(x, SR)
    assert off == 0.0 and len(y) == len(x)


def test_baseline_is_median_and_semitone_iqr():
    f0 = np.array([100.0, 100.0, 200.0, 200.0, np.nan])
    b = baseline_of(f0)
    assert b.hz == pytest.approx(150.0)
    st = 12 * np.log2(np.array([100, 100, 200, 200]) / 150.0)
    q1, q3 = np.percentile(st, [25, 75])
    assert b.spread_st == pytest.approx(q3 - q1)
    assert baseline_of(np.array([np.nan])) is None


def test_baseline_spread_has_a_floor():
    assert baseline_of(np.full(50, 180.0)).spread_st == 1.0


def test_blend_weights_take_and_profile():
    prof, take = Baseline(100.0, 4.0), Baseline(400.0, 8.0)
    assert blend(None, take, 0.2) == take
    assert blend(prof, None, 0.8) == prof
    assert blend(prof, take, 0.0) == prof
    mid = blend(prof, take, 0.5)
    assert mid.hz == pytest.approx(200.0) and mid.spread_st == pytest.approx(6.0)


def test_normalise_is_semitones_over_spread():
    b = Baseline(100.0, 2.0)
    out = normalise(np.array([200.0, np.nan]), b, span=False)
    assert out[0] == pytest.approx(12.0) and np.isnan(out[1])
    assert normalise(np.array([200.0]), b, span=True)[0] == pytest.approx(6.0)
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_pitch.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'shadow.scoring.pitch'`).

- [ ] **Step 4: Implement `backend/shadow/scoring/pitch.py`**

```python
"""Pitch, silence trim and speaker baselines (Phase 2 spec §1 steps 1, 4, 5 and §2)."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np

STEP_S = 0.01
MIN_SPREAD_ST = 1.0          # a monotone take must not blow normalised values up


@dataclass
class Pitch:
    t0: float                # time of frame 0 (s) on the audio's own axis
    f0: np.ndarray           # Hz per 10 ms frame, nan where unvoiced

    def times(self) -> np.ndarray:
        return self.t0 + STEP_S * np.arange(len(self.f0))

    def voiced(self) -> np.ndarray:
        return self.f0[~np.isnan(self.f0)]


def track_pitch(wav: np.ndarray, sr: int, floor: float = 60, ceiling: float = 500) -> Pitch:
    """parselmouth autocorrelation pitch at 10 ms; one retry at 40–600 Hz when under half the frames are voiced,
    kept only if it finds more voiced frames."""
    import parselmouth
    snd = parselmouth.Sound(np.asarray(wav, dtype=np.float64), sampling_frequency=sr)
    p = _ac(snd, floor, ceiling)
    if len(p.f0) and np.mean(~np.isnan(p.f0)) < 0.5:
        q = _ac(snd, 40, 600)
        if np.sum(~np.isnan(q.f0)) > np.sum(~np.isnan(p.f0)):
            p = q
    return p


def _ac(snd, floor: float, ceiling: float) -> Pitch:
    pitch = snd.to_pitch_ac(time_step=STEP_S, pitch_floor=floor, pitch_ceiling=ceiling)
    f0 = np.asarray(pitch.selected_array["frequency"], dtype=float)
    f0[f0 <= 0] = np.nan
    xs = pitch.xs()
    return Pitch(float(xs[0]) if len(xs) else 0.0, f0)


def trim_silence(wav: np.ndarray, sr: int, keep_s: float = 0.05, rel_db: float = -35.0) -> tuple[np.ndarray, float]:
    """Cut leading and trailing 20 ms frames quieter than `rel_db` below the loudest one, keeping `keep_s` of margin
    (the Flow slice slack, main spec §6.1). Returns the samples and the offset (s) of their first one."""
    hop = int(0.02 * sr)
    n = len(wav) // hop
    if n == 0:
        return wav, 0.0
    rms = np.sqrt(np.mean(wav[: n * hop].astype(np.float64).reshape(n, hop) ** 2, axis=1)) + 1e-12
    loud = np.flatnonzero(20 * np.log10(rms / rms.max()) > rel_db)
    a = max(0, int(loud[0] * hop - keep_s * sr))
    b = min(len(wav), int((loud[-1] + 1) * hop + keep_s * sr))
    return wav[a:b], a / sr


@dataclass
class Baseline:
    hz: float                # median voiced F0
    spread_st: float         # interquartile range in semitones around it


def baseline_of(f0: np.ndarray) -> Baseline | None:
    v = f0[np.isfinite(f0) & (f0 > 0)]
    if len(v) == 0:
        return None
    hz = float(np.median(v))
    q1, q3 = np.percentile(12 * np.log2(v / hz), [25, 75])
    return Baseline(hz, max(float(q3 - q1), MIN_SPREAD_ST))


def blend(profile: Baseline | None, take: Baseline | None, w_take: float) -> Baseline | None:
    """`w_take` of the take's own baseline, the rest from the profile (geometric for Hz), spec §2."""
    if profile is None or (w_take >= 1 and take is not None):
        return take if take is not None else profile
    if take is None or w_take <= 0:
        return profile
    hz = float(np.exp(w_take * np.log(take.hz) + (1 - w_take) * np.log(profile.hz)))
    return Baseline(hz, w_take * take.spread_st + (1 - w_take) * profile.spread_st)


def normalise(f0: np.ndarray, base: Baseline, span: bool) -> np.ndarray:
    """Semitones relative to the baseline (nan stays nan), in units of the speaker's spread when `span`."""
    st = 12 * np.log2(f0 / base.hz)
    return st / base.spread_st if span else st
```

- [ ] **Step 5: Run the tests**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_pitch.py -q`
Expected: PASS. If `test_trim_silence_cuts_both_ends_and_reports_the_offset` is off by one frame, fix the implementation, not the bounds.

- [ ] **Step 6: Commit**

```bash
git add backend/shadow/scoring/pitch.py backend/tests/helpers.py backend/tests/test_pitch.py
git commit -m "feat(backend): pitch tracking, silence trim and speaker baselines"
```

---

### Task 3: Syllable contours, classifier features and DTW

**Files:**
- Create: `backend/shadow/scoring/features.py`
- Test: `backend/tests/test_features.py`

**Interfaces:**
- Consumes: `STEP_S` (Task 2).
- Produces:
  - `FEATURE_VERSION = 1`, `POINTS = 20`, `N_FEATURES = 45`
  - `@dataclass SylPitch(contour: np.ndarray | None, voiced_ratio: float, duration: float)`
  - `syllable_pitch(norm: np.ndarray, t0: float, start: float, end: float, min_voiced: int) -> SylPitch`
  - `feature_matrix(sylls: list[SylPitch]) -> np.ndarray` (shape `(len(sylls), N_FEATURES)`, float32)
  - `dtw_distance(a: np.ndarray, b: np.ndarray, band: int) -> float`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_features.py`:
```python
import numpy as np
import pytest
from shadow.scoring.features import (FEATURE_VERSION, N_FEATURES, POINTS, SylPitch, dtw_distance, feature_matrix,
                                     syllable_pitch)


def test_syllable_pitch_trims_and_resamples_voiced_frames():
    norm = np.linspace(-1, 1, 100)                 # 1 s rising line on a 10 ms grid starting at t0 = 0
    s = syllable_pitch(norm, 0.0, 0.0, 1.0, min_voiced=4)
    assert s.contour.shape == (POINTS,) and s.voiced_ratio == 1.0 and s.duration == 1.0
    assert s.contour[0] == pytest.approx(-0.7, abs=0.03) and s.contour[-1] == pytest.approx(0.7, abs=0.03)


def test_syllable_pitch_unvoiced_below_min_frames():
    norm = np.full(100, np.nan); norm[50:53] = 0.0
    s = syllable_pitch(norm, 0.0, 0.0, 1.0, min_voiced=4)
    assert s.contour is None and 0 < s.voiced_ratio < 0.1


def test_syllable_pitch_respects_t0():
    norm = np.concatenate([np.zeros(50), np.ones(50)])
    s = syllable_pitch(norm, 0.5, 0.5, 1.0, min_voiced=4)      # frames 0..49 cover 0.5–1.0 s
    assert np.allclose(s.contour, 0.0)


def test_feature_matrix_shape_and_neighbours():
    up = SylPitch(np.linspace(-1, 1, POINTS), 1.0, 0.2)
    down = SylPitch(np.linspace(1, -1, POINTS), 1.0, 0.2)
    quiet = SylPitch(None, 0.1, 0.1)
    X = feature_matrix([up, down, quiet])
    assert X.shape == (3, N_FEATURES) and X.dtype == np.float32
    assert np.allclose(X[0, :POINTS], up.contour)
    assert not np.allclose(X[0], X[1])
    assert FEATURE_VERSION == 1


def test_feature_matrix_single_syllable_has_empty_neighbours():
    X = feature_matrix([SylPitch(np.zeros(POINTS), 1.0, 0.3)])
    assert X.shape == (1, N_FEATURES) and np.isfinite(X).all()


def test_dtw_distance():
    a = np.sin(np.linspace(0, 3, 20))
    assert dtw_distance(a, a, 4) == 0.0
    assert dtw_distance(a, a + 2.0, 4) == pytest.approx(2.0)
    shifted = np.sin(np.linspace(0.3, 3.3, 20))
    assert dtw_distance(a, shifted, 4) < np.mean(np.abs(a - shifted))
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_features.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `backend/shadow/scoring/features.py`**

```python
"""Per-syllable contours and classifier features (Phase 2 spec §1 step 6, §4.2). The app and the training tool both
call these; any change to what they return must bump FEATURE_VERSION and retrain the tone model."""
from __future__ import annotations
from dataclasses import dataclass
import numpy as np
from shadow.scoring.pitch import STEP_S

FEATURE_VERSION = 1
POINTS = 20
NEIGHBOUR_POINTS = 5
TRIM = 0.15
_OWN = POINTS + 6 + 3                    # contour, its summary, voiced ratio / relative duration / position
_NEIGHBOUR = NEIGHBOUR_POINTS + 3        # 5-point contour, mean, voiced ratio, present flag
N_FEATURES = _OWN + 2 * _NEIGHBOUR


@dataclass
class SylPitch:
    contour: np.ndarray | None           # POINTS normalised values; None when unvoiced
    voiced_ratio: float
    duration: float


def syllable_pitch(norm: np.ndarray, t0: float, start: float, end: float, min_voiced: int) -> SylPitch:
    """The syllable's [start, end] with 15 % trimmed at each end, its voiced frames interpolated to POINTS values."""
    dur = max(end - start, 0.0)
    a, b = start + TRIM * dur, end - TRIM * dur
    times = t0 + STEP_S * np.arange(len(norm))
    sel = (times >= a) & (times <= b)
    seg, t = norm[sel], times[sel]
    ok = np.isfinite(seg)
    ratio = float(ok.mean()) if len(seg) else 0.0
    if ok.sum() < min_voiced:
        return SylPitch(None, ratio, dur)
    return SylPitch(np.interp(np.linspace(a, b, POINTS), t[ok], seg[ok]), ratio, dur)


def _summary(c: np.ndarray) -> list[float]:
    h, x = POINTS // 2, np.arange(POINTS // 2)
    return [float(c.mean()), float(np.polyfit(x, c[:h], 1)[0]), float(np.polyfit(x, c[h:], 1)[0]),
            float(c.min()), float(c.max()), float(np.argmin(c)) / (POINTS - 1)]


def _neighbour(s: SylPitch | None) -> list[float]:
    if s is None:
        return [0.0] * _NEIGHBOUR
    if s.contour is None:
        return [0.0] * NEIGHBOUR_POINTS + [0.0, s.voiced_ratio, 1.0]
    pts = np.interp(np.linspace(0, POINTS - 1, NEIGHBOUR_POINTS), np.arange(POINTS), s.contour)
    return [*pts.tolist(), float(s.contour.mean()), s.voiced_ratio, 1.0]


def feature_matrix(sylls: list[SylPitch]) -> np.ndarray:
    """One row per syllable. Unvoiced syllables get a zero contour; callers do not classify them."""
    n = len(sylls)
    mean_dur = float(np.mean([s.duration for s in sylls])) if n else 1.0
    rows = []
    for i, s in enumerate(sylls):
        c = s.contour if s.contour is not None else np.zeros(POINTS)
        own = [*c.tolist(), *_summary(c), s.voiced_ratio, s.duration / (mean_dur or 1.0), i / max(n - 1, 1)]
        rows.append(own + _neighbour(sylls[i - 1] if i > 0 else None) + _neighbour(sylls[i + 1] if i < n - 1 else None))
    return np.asarray(rows, dtype=np.float32).reshape(n, N_FEATURES)


def dtw_distance(a: np.ndarray, b: np.ndarray, band: int) -> float:
    """Mean absolute difference along the cheapest warping path inside a Sakoe–Chiba band."""
    n, m = len(a), len(b)
    cost = np.full((n + 1, m + 1), np.inf)
    steps = np.zeros((n + 1, m + 1))
    cost[0, 0] = 0.0
    for i in range(1, n + 1):
        for j in range(max(1, i - band), min(m, i + band) + 1):
            prev = min(((i - 1, j - 1), (i - 1, j), (i, j - 1)), key=lambda p: cost[p])
            cost[i, j] = cost[prev] + abs(float(a[i - 1]) - float(b[j - 1]))
            steps[i, j] = steps[prev] + 1
    return float(cost[n, m] / steps[n, m])
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_features.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/shadow/scoring/features.py backend/tests/test_features.py
git commit -m "feat(backend): syllable contours, tone features and banded DTW"
```

---

### Task 4: Tone model interface and verdict rules

**Files:**
- Create: `backend/shadow/scoring/tone.py`
- Test: `backend/tests/test_tone.py`

**Interfaces:**
- Consumes: `FEATURE_VERSION` (Task 3), `dtw_distance` (Task 3), `ScoringCfg` (Task 1).
- Produces:
  - `TONES = (0, 1, 2, 3, 4)`
  - `class ToneModel(Protocol)`: attributes `version: str`, `dtw_norm: float`, `meta: dict`; method `proba(X: np.ndarray) -> np.ndarray` (shape `(n, 5)`, columns in `TONES` order)
  - `FakeToneModel(tone: int = 1, p: float = 0.9, dtw_norm: float = 1.0)`; `SklearnToneModel(clf, meta: dict)`
  - `MODELS_DIR: Path`; `load_tone_model(name: str, models_dir: Path = MODELS_DIR) -> ToneModel | None`
  - `target_tone(ref_p: np.ndarray | None, canonical: int, min_conf: float) -> int`
  - `contour_similarity(ref: np.ndarray, usr: np.ndarray, band: int, norm: float) -> float`
  - `@dataclass Verdict(status: str, tone_score: float, p_target: float, contour: float | None, heard: int)`; `judge(p_usr: np.ndarray, target: int, contour: float | None, cfg: ScoringCfg) -> Verdict`
  - `sentence_overall(items: list[tuple[str, float | None]]) -> float | None`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_tone.py`:
```python
import json
import numpy as np
import pytest
from shadow.config import ScoringCfg
from shadow.scoring.tone import (TONES, FakeToneModel, contour_similarity, judge, load_tone_model, sentence_overall,
                                 target_tone)

CFG = ScoringCfg()


def p_of(**probs):
    row = np.zeros(5)
    for k, v in probs.items():
        row[TONES.index(int(k[1:]))] = v
    return row


def test_fake_model_shape_and_order():
    P = FakeToneModel(tone=3, p=0.8).proba(np.zeros((2, 45)))
    assert P.shape == (2, 5) and np.allclose(P.sum(axis=1), 1.0) and P[0, TONES.index(3)] == pytest.approx(0.8)


def test_target_tone_uses_a_confident_reference_else_canonical():
    assert target_tone(p_of(t2=0.7, t3=0.3), canonical=3, min_conf=0.6) == 2     # 3-3 sandhi heard as 2
    assert target_tone(p_of(t2=0.5, t3=0.5), canonical=3, min_conf=0.6) == 3
    assert target_tone(None, canonical=4, min_conf=0.6) == 4


def test_contour_similarity_is_scaled_and_clamped():
    a = np.zeros(20)
    assert contour_similarity(a, a, 4, norm=1.0) == 1.0
    assert contour_similarity(a, a + 0.1, 4, norm=1.0) == pytest.approx(0.9)
    assert contour_similarity(a, a + 5, 4, norm=1.0) == 0.0


def test_judge_ok_close_wrong():
    ok = judge(p_of(t4=0.9, t1=0.1), target=4, contour=0.9, cfg=CFG)
    assert (ok.status, ok.heard) == ("ok", 4) and ok.tone_score == pytest.approx(0.9)
    close = judge(p_of(t4=0.6, t1=0.4), target=4, contour=0.3, cfg=CFG)
    assert close.status == "close" and close.tone_score == pytest.approx(0.45)
    wrong = judge(p_of(t2=0.8, t3=0.2), target=3, contour=0.4, cfg=CFG)
    assert (wrong.status, wrong.heard) == ("wrong", 2)
    unsure = judge(p_of(t2=0.5, t3=0.4, t1=0.1), target=3, contour=0.9, cfg=CFG)
    assert unsure.status == "close"                    # another tone wins, but by less than wrong_margin


def test_judge_neutral_target_ignores_contour():
    v = judge(p_of(t0=0.8, t1=0.2), target=0, contour=0.0, cfg=CFG)
    assert v.tone_score == pytest.approx(0.8) and v.status == "ok"


def test_sentence_overall():
    assert sentence_overall([("ok", 0.9), ("missing", None), ("unvoiced", None), ("close", 0.6)]) == pytest.approx(0.5)
    assert sentence_overall([("unvoiced", None)]) is None
    assert sentence_overall([]) is None


def test_load_tone_model_rejects_missing_and_mismatched(tmp_path):
    assert load_tone_model("nope", tmp_path) is None
    (tmp_path / "m.json").write_text(json.dumps({"version": "m", "feature_version": 999, "dtw_norm": 1.0}))
    (tmp_path / "m.joblib").write_bytes(b"x")
    assert load_tone_model("m", tmp_path) is None


def test_load_tone_model_reorders_classes(tmp_path):
    import joblib
    from sklearn.dummy import DummyClassifier
    from shadow.scoring.features import FEATURE_VERSION
    X = np.zeros((5, 3)); y = np.array([4, 3, 2, 1, 0])
    clf = DummyClassifier(strategy="prior").fit(X, y)
    joblib.dump(clf, tmp_path / "m.joblib")
    (tmp_path / "m.json").write_text(json.dumps({"version": "m1", "feature_version": FEATURE_VERSION, "dtw_norm": 2.0}))
    m = load_tone_model("m", tmp_path)
    assert m.version == "m1" and m.dtw_norm == 2.0 and m.proba(np.zeros((1, 3))).shape == (1, 5)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_tone.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `backend/shadow/scoring/tone.py`**

```python
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
    """The shipped model, or None (scores then carry `no_tone_model`) when it is missing or built for other features."""
    meta_p, model_p = models_dir / f"{name}.json", models_dir / f"{name}.joblib"
    if not (meta_p.exists() and model_p.exists()):
        log.warning("tone model %s not found in %s", name, models_dir)
        return None
    meta = json.loads(meta_p.read_text())
    if meta.get("feature_version") != FEATURE_VERSION:
        log.warning("tone model %s has feature version %s, the app %s", name, meta.get("feature_version"), FEATURE_VERSION)
        return None
    import joblib
    return SklearnToneModel(joblib.load(model_p), meta)


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
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_tone.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/shadow/scoring/tone.py backend/tests/test_tone.py
git commit -m "feat(backend): tone model interface, target tone and verdict rules"
```

---

### Task 5: Quality gate and a serialised aligner

**Files:**
- Create: `backend/shadow/scoring/gate.py`
- Modify: `backend/shadow/ingest/align.py` (add `LockedAligner`), `backend/shadow/deps.py`
- Test: `backend/tests/test_gate.py`, `backend/tests/test_align.py`

**Interfaces:**
- Consumes: `ScoringCfg` (Task 1), `Span`, `Aligner` (existing `shadow.ingest.align`).
- Produces:
  - `level_dbfs(wav: np.ndarray) -> float`; `clipped_ratio(wav: np.ndarray) -> float`
  - `pre_gate(wav: np.ndarray, sr: int, ref_speech_s: float, cfg: ScoringCfg) -> list[str]` (codes `too_short`, `too_quiet`, `clipped`)
  - `align_gate(spans: list[Span], cfg: ScoringCfg) -> list[str]` (code `wrong_or_unclear`)
  - `LockedAligner(inner: Aligner)` with `.align(...)` and a read-only `._model` passthrough; `build_deps` wraps its aligner in it.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_gate.py`:
```python
import numpy as np
from shadow.config import ScoringCfg
from shadow.ingest.align import Span
from shadow.scoring.gate import align_gate, clipped_ratio, level_dbfs, pre_gate
from tests.helpers import voice

SR, CFG = 16000, ScoringCfg()


def test_good_take_passes():
    assert pre_gate(voice([(200, 200)], syl_s=1.0), SR, ref_speech_s=1.2, cfg=CFG) == []


def test_too_short_too_quiet_clipped():
    assert "too_short" in pre_gate(voice([(200, 200)], syl_s=0.3), SR, ref_speech_s=1.0, cfg=CFG)
    assert "too_quiet" in pre_gate(voice([(200, 200)], syl_s=1.0) * 0.001, SR, ref_speech_s=1.0, cfg=CFG)
    loud = np.clip(voice([(200, 200)], syl_s=1.0) * 20, -1, 1)
    assert "clipped" in pre_gate(loud, SR, ref_speech_s=1.0, cfg=CFG)


def test_levels():
    assert level_dbfs(np.zeros(100)) < -100
    assert abs(level_dbfs(np.full(100, 0.5)) - (-6.02)) < 0.1
    assert clipped_ratio(np.array([1.0, -1.0, 0.0, 0.2])) == 0.5


def test_align_gate_on_mean_confidence():
    good = [Span("我", 0, 0.2, 0.8), Span("们", 0.2, 0.4, 0.6)]
    bad = [Span("我", 0, 0.2, 0.1), Span("们", 0.2, 0.4, 0.1)]
    assert align_gate(good, CFG) == [] and align_gate(bad, CFG) == ["wrong_or_unclear"]
```

Append to `backend/tests/test_align.py`:
```python
def test_locked_aligner_serialises_calls():
    import threading, time
    import numpy as np
    from shadow.ingest.align import LockedAligner

    class Slow:
        _model = "m"
        def __init__(self): self.active = 0; self.peak = 0
        def align(self, wav, sr, text):
            self.active += 1; self.peak = max(self.peak, self.active); time.sleep(0.05); self.active -= 1
            return []

    inner = Slow(); la = LockedAligner(inner)
    ts = [threading.Thread(target=la.align, args=(np.zeros(10), 16000, "我")) for _ in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert inner.peak == 1 and la._model == "m"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_gate.py tests/test_align.py -q`
Expected: FAIL (module / name not found).

- [ ] **Step 3: Implement**

`backend/shadow/scoring/gate.py`:
```python
"""Quality gate (Phase 2 spec §1 step 2): takes that cannot be scored meaningfully come back as warnings instead."""
from __future__ import annotations
import numpy as np
from shadow.config import ScoringCfg
from shadow.ingest.align import Span


def level_dbfs(wav: np.ndarray) -> float:
    return float(20 * np.log10(np.sqrt(np.mean(np.asarray(wav, dtype=np.float64) ** 2)) + 1e-12)) if len(wav) else -240.0


def clipped_ratio(wav: np.ndarray) -> float:
    return float(np.mean(np.abs(wav) >= 0.999)) if len(wav) else 0.0


def pre_gate(wav: np.ndarray, sr: int, ref_speech_s: float, cfg: ScoringCfg) -> list[str]:
    """Checks on the trimmed take before any alignment or pitch call (parselmouth raises on very short sounds)."""
    out = []
    if len(wav) / sr < max(cfg.min_duration_ratio * ref_speech_s, 0.15):
        out.append("too_short")
    if level_dbfs(wav) < cfg.min_rms_dbfs:
        out.append("too_quiet")
    if clipped_ratio(wav) > cfg.max_clipped:
        out.append("clipped")
    return out


def align_gate(spans: list[Span], cfg: ScoringCfg) -> list[str]:
    """A wrong or garbled sentence aligns with low confidence."""
    if spans and float(np.mean([s.conf for s in spans])) < cfg.min_align_conf:
        return ["wrong_or_unclear"]
    return []
```

`backend/shadow/ingest/align.py` — add `import threading` to the imports and, after `class Aligner(Protocol)`, add:
```python
class LockedAligner:
    """One aligner shared by ingest jobs and attempt scoring (Phase 2 spec §1 step 3): calls run one at a time."""
    def __init__(self, inner: Aligner):
        self.inner = inner
        self._lock = threading.Lock()

    @property
    def _model(self):                   # Deps.loaded_models() looks for it
        return getattr(self.inner, "_model", None)

    def align(self, wav: np.ndarray, sr: int, text: str) -> list[Span]:
        with self._lock:
            return self.inner.align(wav, sr, text)
```

`backend/shadow/deps.py` — import `LockedAligner` from `shadow.ingest.align` and in `build_deps` change the aligner argument to `aligner=LockedAligner(make_aligner(settings.resolved_aligner(), device))`. Then check nothing type-checks the concrete aligner class:
```bash
cd backend && grep -rn "isinstance(.*aligner\|MmsAligner)\|Qwen3Aligner)" shadow scripts
```
Expected: no matches outside `align.py` itself (if there are, unwrap with `.inner` there).

- [ ] **Step 4: Run the tests**

Run: `cd backend && ~/.local/bin/uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/shadow/scoring/gate.py backend/shadow/ingest/align.py backend/shadow/deps.py backend/tests/test_gate.py backend/tests/test_align.py
git commit -m "feat(backend): scoring quality gate; one aligner call at a time"
```

---

### Task 6: Score one take (`score_take`)

**Files:**
- Create: `backend/shadow/scoring/score.py`
- Test: `backend/tests/test_score.py`

**Interfaces:**
- Consumes: Tasks 2–5 (`trim_silence`, `track_pitch`, `baseline_of`, `blend`, `normalise`, `Pitch`, `Baseline`, `syllable_pitch`, `feature_matrix`, `FEATURE_VERSION`, `ToneModel`, `target_tone`, `contour_similarity`, `judge`, `sentence_overall`, `pre_gate`, `align_gate`, `level_dbfs`, `clipped_ratio`); `Aligner` (existing).
- Produces:
  - `@dataclass RefData(pitch: Pitch, spans: list[tuple[float, float]], baseline: Baseline)` — reference pitch and syllable spans on the clip's own time axis, lesson-wide baseline.
  - `@dataclass TakeResult(json: dict, rows: list[dict], voiced_f0: np.ndarray)` — `rows` hold `SyllableScore` fields except `attempt_id`/`segment_id`: `idx, ch, pinyin_toneless, tone, prev_tone, target_tone, heard_tone, tone_score, status`.
  - `score_take(*, ref: RefData, syllables: list[dict], text: str, wav: np.ndarray, sr: int, aligner: Aligner, model: ToneModel | None, profile: Baseline | None, profile_voiced_s: float, cfg: ScoringCfg) -> TakeResult`
  - `failed_result(syllables: list[dict], warnings: list[str], quality: dict | None = None) -> TakeResult`
  - `syllables` items are `words_json` syllables: `{"ch", "pinyin", "pinyin_toneless", "tone"}`.

Score JSON keys (spec §5.1): `overall, tone_overall, segmental_overall, rate_ratio, ref_contour, usr_contour, syllables, pitch_range_st, warnings, quality, model_version, feature_version`. Each syllable: `ch, pinyin, tone, target_tone, heard_tone, status, tone_score, p_target, contour, seg_score, ref_f0, usr_f0, ref_dur, usr_dur`. Contours: `{"t0_s", "step_ms": 10, "f0_st": [float | None], "spans": [[start_s, end_s], …]}`. `quality`: `{"dbfs", "clipped", "align_conf"}` (diagnostics for Task 15's thresholds).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_score.py`:
```python
import numpy as np
import pytest
from shadow.config import ScoringCfg
from shadow.ingest.align import FakeAligner, Span
from shadow.scoring.pitch import baseline_of, track_pitch
from shadow.scoring.score import RefData, score_take
from shadow.scoring.tone import FakeToneModel
from tests.helpers import voice

SR, CFG = 16000, ScoringCfg()
TEXT = "今天中心"                                   # jīn tiān zhōng xīn: all tone 1
SYLS = [{"ch": c, "pinyin": p, "pinyin_toneless": p, "tone": 1} for c, p in zip(TEXT, ["jin", "tian", "zhong", "xin"])]
REF_CONTOURS = [(220, 220), (150, 300), (300, 150), (220, 220)]


def ref_data(contours=REF_CONTOURS):
    wav = voice(contours)
    p = track_pitch(wav, SR)
    spans = [(s.start, s.end) for s in FakeAligner().align(wav, SR, TEXT)]
    return RefData(p, spans, baseline_of(p.voiced()))


def run(take, *, syllables=SYLS, text=TEXT, model=FakeToneModel(tone=1, p=0.9), aligner=FakeAligner(), **kw):
    return score_take(ref=ref_data(), syllables=syllables, text=text, wav=take, sr=SR, aligner=aligner, model=model,
                      profile=kw.get("profile"), profile_voiced_s=kw.get("voiced_s", 0.0), cfg=CFG)


def test_matching_take_is_all_ok():
    r = run(voice(REF_CONTOURS, lead_s=0.3))
    assert [s["status"] for s in r.json["syllables"]] == ["ok"] * 4
    assert r.json["overall"] == pytest.approx(r.json["tone_overall"]) and r.json["overall"] > 0.9
    assert r.json["warnings"] == [] and r.json["segmental_overall"] is None
    assert len(r.rows) == 4 and r.rows[1]["prev_tone"] == 1 and r.rows[0]["prev_tone"] is None
    assert len(r.voiced_f0) > 50


def test_an_inverted_syllable_loses_only_its_contour():
    take = voice([(220, 220), (300, 150), (300, 150), (220, 220)])       # syllable 2 falls instead of rising
    syl = run(take).json["syllables"]
    assert syl[1]["contour"] < 0.5 and syl[1]["status"] == "close"
    assert all(syl[i]["status"] == "ok" for i in (0, 2, 3))


def test_usr_contour_is_on_the_stored_take_axis():
    r = run(voice(REF_CONTOURS, lead_s=0.4))
    c = r.json["usr_contour"]
    assert c["step_ms"] == 10 and len(c["spans"]) == 4
    assert 0.35 <= c["spans"][0][0] <= 0.45                              # trim offset added back
    assert c["t0_s"] >= 0.3                                                # the trimmed take starts ~0.35 s in


def test_tiny_take_is_gated_before_pitch(monkeypatch):
    import shadow.scoring.score as score
    monkeypatch.setattr(score, "track_pitch", lambda *a, **k: (_ for _ in ()).throw(AssertionError("pitch called")))
    r = score_take(ref=ref_data(), syllables=SYLS, text=TEXT, wav=voice([(200, 200)], syl_s=0.1), sr=SR,
                   aligner=FakeAligner(), model=FakeToneModel(), profile=None, profile_voiced_s=0.0, cfg=CFG)
    assert r.json["overall"] is None and "too_short" in r.json["warnings"] and r.rows == []
    assert [s["status"] for s in r.json["syllables"]] == ["missing"] * 4


def test_silence_is_too_quiet():
    r = run(np.zeros(SR, dtype="float32"))
    assert "too_quiet" in r.json["warnings"] and r.rows == []


def test_no_model_scores_nothing():
    r = run(voice(REF_CONTOURS), model=None)
    assert r.json["overall"] is None and r.json["warnings"] == ["no_tone_model"] and r.rows == []


def test_span_count_mismatch_is_align_failed():
    class Short:
        def align(self, wav, sr, text): return [Span("今", 0.0, 0.5, 1.0)]
    r = run(voice(REF_CONTOURS), aligner=Short())
    assert r.json["warnings"] == ["align_failed"] and r.json["overall"] is None


def test_low_confidence_alignment_is_wrong_or_unclear():
    class Unsure:
        def align(self, wav, sr, text): return [Span(s.ch, s.start, s.end, 0.05) for s in FakeAligner().align(wav, sr, text)]
    r = run(voice(REF_CONTOURS), aligner=Unsure())
    assert r.json["warnings"] == ["wrong_or_unclear"] and r.json["quality"]["align_conf"] == pytest.approx(0.05)


def test_zero_length_learner_span_is_missing():
    class Collapsed:
        def align(self, wav, sr, text):
            sp = FakeAligner().align(wav, sr, text)
            sp[2] = Span(sp[2].ch, sp[2].start, sp[2].start, 1.0)
            return sp
    r = run(voice(REF_CONTOURS), aligner=Collapsed())
    syl = r.json["syllables"]
    assert syl[2]["status"] == "missing" and syl[2]["tone_score"] == 0.0
    assert r.rows[2]["status"] == "missing"


def test_non_hanzi_syllable_is_unvoiced():
    syls = SYLS[:3] + [{"ch": "A", "pinyin": "A", "pinyin_toneless": "A", "tone": -1}]
    r = run(voice(REF_CONTOURS), syllables=syls, text="今天中A")
    assert r.json["syllables"][3]["status"] == "unvoiced" and r.json["syllables"][3]["tone_score"] is None


def test_wrong_tone_shows_heard_tone():
    r = run(voice(REF_CONTOURS), model=FakeToneModel(tone=2, p=0.9))
    # the reference is also 'heard' as 2 by this fake, so the target becomes 2 and the take matches it
    assert {s["target_tone"] for s in r.json["syllables"]} == {2}
    low_ref = FakeToneModel(tone=2, p=0.55)            # under ref_confidence → canonical target 1
    r2 = run(voice(REF_CONTOURS), model=low_ref)
    s = r2.json["syllables"][0]
    assert s["target_tone"] == 1 and s["heard_tone"] == 2 and s["status"] == "wrong"


def test_profile_sets_the_learner_baseline_once_it_has_enough_speech():
    from shadow.scoring.pitch import Baseline
    take = voice(REF_CONTOURS)
    alone = run(take).json["usr_contour"]["f0_st"]
    with_profile = run(take, profile=Baseline(110.0, 3.0), voiced_s=600.0).json["usr_contour"]["f0_st"]
    a = np.array([v for v in alone if v is not None]); b = np.array([v for v in with_profile if v is not None])
    assert b.mean() > a.mean() + 1                     # a 110 Hz baseline puts a 220 Hz take high above it
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_score.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `backend/shadow/scoring/score.py`**

```python
"""Score one take against its reference (Phase 2 spec §1, §3). Pure: no database, no files."""
from __future__ import annotations
from dataclasses import dataclass, field
import numpy as np
from shadow.config import ScoringCfg
from shadow.ingest.align import Aligner
from shadow.scoring.features import FEATURE_VERSION, SylPitch, feature_matrix, syllable_pitch
from shadow.scoring.gate import align_gate, clipped_ratio, level_dbfs, pre_gate
from shadow.scoring.pitch import Baseline, Pitch, baseline_of, blend, normalise, track_pitch, trim_silence
from shadow.scoring.tone import ToneModel, contour_similarity, judge, sentence_overall, target_tone

MIN_SPAN_S = 0.03                         # a learner span shorter than this was skipped or collapsed: missing


@dataclass
class RefData:
    pitch: Pitch                          # on the clip's own time axis
    spans: list[tuple[float, float]]      # each syllable's [start, end] on the same axis
    baseline: Baseline                    # the speaker over the whole lesson (spec §2)


@dataclass
class TakeResult:
    json: dict
    rows: list[dict] = field(default_factory=list)
    voiced_f0: np.ndarray = field(default_factory=lambda: np.zeros(0))


def _syl_json(s: dict, status: str, **kw) -> dict:
    base = {"ch": s["ch"], "pinyin": s.get("pinyin", ""), "tone": s["tone"], "target_tone": None, "heard_tone": None,
            "status": status, "tone_score": None, "p_target": None, "contour": None, "seg_score": None,
            "ref_f0": None, "usr_f0": None, "ref_dur": None, "usr_dur": None}
    return {**base, **kw}


def failed_result(syllables: list[dict], warnings: list[str], quality: dict | None = None,
                  model_version: str | None = None) -> TakeResult:
    """No score: every syllable missing, no rows, so stats and the voice profile ignore the take."""
    return TakeResult({"overall": None, "tone_overall": None, "segmental_overall": None, "rate_ratio": None,
                       "ref_contour": None, "usr_contour": None, "syllables": [_syl_json(s, "missing") for s in syllables],
                       "pitch_range_st": None, "warnings": warnings, "quality": quality,
                       "model_version": model_version, "feature_version": FEATURE_VERSION})


def _contour_json(t0: float, norm: np.ndarray, spans: list[tuple[float, float]]) -> dict:
    return {"t0_s": round(t0, 3), "step_ms": 10,
            "f0_st": [None if not np.isfinite(v) else round(float(v), 3) for v in norm],
            "spans": [[round(a, 3), round(b, 3)] for a, b in spans]}


def _r(x: float | None, nd: int = 3) -> float | None:
    return None if x is None else round(float(x), nd)


def score_take(*, ref: RefData, syllables: list[dict], text: str, wav: np.ndarray, sr: int, aligner: Aligner,
               model: ToneModel | None, profile: Baseline | None, profile_voiced_s: float, cfg: ScoringCfg) -> TakeResult:
    trimmed, off = trim_silence(wav, sr)
    ref_speech_s = ref.spans[-1][1] - ref.spans[0][0] if ref.spans else 0.0
    quality = {"dbfs": round(level_dbfs(trimmed), 1), "clipped": round(clipped_ratio(trimmed), 4), "align_conf": None}
    if warnings := pre_gate(trimmed, sr, ref_speech_s, cfg):
        return failed_result(syllables, warnings, quality)
    if model is None:
        return failed_result(syllables, ["no_tone_model"], quality)
    spans = aligner.align(trimmed, sr, text)
    if len(spans) != len(syllables) or len(ref.spans) != len(syllables):
        return failed_result(syllables, ["align_failed"], quality, model.version)
    quality["align_conf"] = round(float(np.mean([s.conf for s in spans])), 3) if spans else None
    if warnings := align_gate(spans, cfg):
        return failed_result(syllables, warnings, quality, model.version)

    pitch = track_pitch(trimmed, sr, cfg.f0_floor, cfg.f0_ceiling)
    w_take = max(0.0, 1.0 - profile_voiced_s / cfg.profile_seconds)
    base = blend(profile, baseline_of(pitch.voiced()), w_take)
    if base is None:
        return failed_result(syllables, ["no_voice"], quality, model.version)
    norm_r = normalise(ref.pitch.f0, ref.baseline, cfg.normalise_span)
    norm_u = normalise(pitch.f0, base, cfg.normalise_span)
    syl_r = [syllable_pitch(norm_r, ref.pitch.t0, a, b, cfg.min_voiced_frames) for a, b in ref.spans]
    syl_u = [syllable_pitch(norm_u, pitch.t0, s.start, s.end, cfg.min_voiced_frames) for s in spans]
    P_r, P_u = model.proba(feature_matrix(syl_r)), model.proba(feature_matrix(syl_u))

    out_syl, rows, prev = [], [], None
    for i, (s, r, u) in enumerate(zip(syllables, syl_r, syl_u)):
        common = {"ref_dur": _r(r.duration), "usr_dur": _r(u.duration),
                  "ref_f0": None if r.contour is None else [_r(v) for v in r.contour],
                  "usr_f0": None if u.contour is None else [_r(v) for v in u.contour]}
        if u.duration < MIN_SPAN_S:
            js = _syl_json(s, "missing", tone_score=0.0, **common)
            target = heard = None
        elif s["tone"] < 0 or r.contour is None or u.contour is None:
            js = _syl_json(s, "unvoiced", **common)
            target = heard = None
        else:
            target = target_tone(P_r[i], s["tone"], cfg.ref_confidence)
            sim = None if target == 0 else contour_similarity(r.contour, u.contour, cfg.dtw_band, model.dtw_norm)
            v = judge(P_u[i], target, sim, cfg)
            heard = v.heard
            js = _syl_json(s, v.status, target_tone=target, heard_tone=heard, tone_score=_r(v.tone_score),
                           p_target=_r(v.p_target), contour=_r(v.contour), **common)
        out_syl.append(js)
        rows.append({"idx": i, "ch": s["ch"], "pinyin_toneless": s.get("pinyin_toneless", ""), "tone": s["tone"],
                     "prev_tone": prev, "target_tone": target, "heard_tone": heard,
                     "tone_score": js["tone_score"], "status": js["status"]})
        prev = target if target is not None else s["tone"]

    overall = sentence_overall([(x["status"], x["tone_score"]) for x in out_syl])
    usr_spans = [(s.start + off, s.end + off) for s in spans]
    return TakeResult({
        "overall": _r(overall), "tone_overall": _r(overall), "segmental_overall": None,
        "rate_ratio": _r((spans[-1].end - spans[0].start) / ref_speech_s) if ref_speech_s > 0 else None,
        "ref_contour": _contour_json(ref.pitch.t0, norm_r, ref.spans),
        "usr_contour": _contour_json(pitch.t0 + off, norm_u, usr_spans),
        "syllables": out_syl, "pitch_range_st": {"ref": _r(ref.baseline.spread_st), "usr": _r(base.spread_st)},
        "warnings": [], "quality": quality, "model_version": model.version, "feature_version": FEATURE_VERSION,
    }, rows, pitch.voiced())
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_score.py -q`
Expected: PASS. If `test_an_inverted_syllable_loses_only_its_contour` fails because a neighbour also drops below `green_at`, print the per-syllable `contour` values: neighbouring syllables share DTW edges only through the 15 % trim, so a neighbour below 0.9 means the trim or `syllable_pitch` slicing is wrong — fix that, do not loosen the test.

- [ ] **Step 5: Commit**

```bash
git add backend/shadow/scoring/score.py backend/tests/test_score.py
git commit -m "feat(backend): score one take per syllable against its reference"
```

---

### Task 7: AISHELL-3 reader and the training tool

**Files:**
- Create: `backend/shadow/scoring/corpus.py`, `backend/scripts/tone_model.py`
- Modify: `Makefile`
- Test: `backend/tests/test_corpus.py`

**Interfaces:**
- Consumes: `syllables_for` (existing `shadow.ingest.enrich`, returns `[{"ch", "pinyin", "pinyin_toneless", "tone"}]` with sandhi applied); Tasks 2–4.
- Produces:
  - `@dataclass Utterance(speaker: str, wav: Path, chars: list[str], toneless: list[str | None], tones: list[int | None])`
  - `parse_label(label: str) -> tuple[str, int] | None` (`"hao3"` → `("hao", 3)`, `"ma5"` → `("ma", 0)`, anything else → None)
  - `read_split(split_dir: Path) -> list[Utterance]` (reads `<split_dir>/content.txt`; wavs at `<split_dir>/wav/<speaker>/<name>`)
  - `realise(u: Utterance) -> list[int | None]` (canonical labels → realised tones, via `syllables_for`)
  - `scripts/tone_model.py` CLI: `--root` (default `<data_dir>/corpora/aishell3`), `--hours` (30), `--labels canonical|realised` (required), `--name` (`tone_v1`), `--stage all|features|train` (`all`).
  - Make target `tone-model`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_corpus.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_corpus.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement `backend/shadow/scoring/corpus.py`**

```python
"""AISHELL-3 transcripts for training the tone model (Phase 2 spec §4.1). Training only; the app never imports it."""
from __future__ import annotations
import re
from dataclasses import dataclass
from pathlib import Path
from shadow.ingest.enrich import syllables_for

_LABEL = re.compile(r"([a-zü]+)([1-5])")


@dataclass
class Utterance:
    speaker: str
    wav: Path
    chars: list[str]
    toneless: list[str | None]
    tones: list[int | None]              # 0 neutral; None where the label is not a plain toned syllable (erhua etc.)


def parse_label(label: str) -> tuple[str, int] | None:
    m = _LABEL.fullmatch(label.lower())
    if not m:
        return None
    t = int(m.group(2))
    return m.group(1), 0 if t == 5 else t


def read_split(split_dir: Path) -> list[Utterance]:
    """`content.txt` lines: `SSB00050001.wav<TAB>广 guang3 州 zhou1 …` (character, pinyin pairs)."""
    out = []
    for line in (split_dir / "content.txt").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 3 or len(parts) % 2 == 0 or not parts[0].endswith(".wav"):
            continue
        name, toks = parts[0], parts[1:]
        labels = [parse_label(p) for p in toks[1::2]]
        spk = name[:7]
        out.append(Utterance(spk, split_dir / "wav" / spk / name, toks[0::2],
                             [lb[0] if lb else None for lb in labels], [lb[1] if lb else None for lb in labels]))
    return out


def realise(u: Utterance) -> list[int | None]:
    """Canonical labels → the tones a speaker produces (3-3, 一, 不 sandhi), from the same pypinyin call as enrich;
    a character whose syllable pypinyin reads differently keeps its label."""
    try:
        syl = syllables_for("".join(u.chars))
    except ValueError:
        return list(u.tones)
    return [s["tone"] if t is not None and s["pinyin_toneless"] == tl else t
            for s, t, tl in zip(syl, u.tones, u.toneless)]
```

- [ ] **Step 4: Run the tests**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_corpus.py -q`
Expected: PASS. If `realise(utts[1])` disagrees on 一 (pypinyin versions differ on 一 sandhi), print `syllables_for("一个儿")` and assert what pypinyin actually returns for 一个 with `tone_sandhi=True`; keep the 你好 assertion as is.

- [ ] **Step 5: Write `backend/scripts/tone_model.py`**

```python
"""Train the tone classifier on AISHELL-3 (Phase 2 spec §4). Run once; the two output files are committed.

    cd backend && ~/.local/bin/uv run python scripts/tone_model.py --labels canonical
Stages, each resumable: download and unpack (~19 GB, curl -C) → per-speaker features cached under
<root>/features_v<FEATURE_VERSION>/ → train → evaluate on held-out speakers → write
shadow/scoring/models/<name>.{joblib,json}. Alignment needs the models extra and the GPU (~1–2 h for 30 h)."""
from __future__ import annotations
import argparse
import json
import random
import subprocess
import tarfile
from collections import defaultdict
from datetime import date
from pathlib import Path
import numpy as np
import soundfile as sf
from shadow.config import load_settings
from shadow.ingest.align import make_aligner
from shadow.scoring.corpus import Utterance, read_split, realise
from shadow.scoring.features import FEATURE_VERSION, N_FEATURES, POINTS, dtw_distance, feature_matrix, syllable_pitch
from shadow.scoring.pitch import baseline_of, normalise, track_pitch
from shadow.scoring.tone import MODELS_DIR, TONES

URL = "https://www.openslr.org/resources/93/data_aishell3.tgz"
TEST_SHARE = 0.15
MAX_PAIRS = 20000


def download(root: Path) -> None:
    if list(root.rglob("content.txt")):
        return
    root.mkdir(parents=True, exist_ok=True)
    tgz = root / "data_aishell3.tgz"
    subprocess.run(["curl", "-L", "-C", "-", "-o", str(tgz), URL], check=True)
    with tarfile.open(tgz) as t:
        t.extractall(root, filter="data")
    tgz.unlink()


def pick(root: Path, hours: float) -> list[Utterance]:
    """A fixed random subset of all utterances (both official splits) adding up to `hours`."""
    utts = [u for c in sorted(root.rglob("content.txt")) for u in read_split(c.parent)]
    random.Random(0).shuffle(utts)
    out, total = [], 0.0
    for u in utts:
        if total >= hours * 3600:
            break
        if u.wav.exists():
            total += sf.info(u.wav).duration
            out.append(u)
    print(f"{len(out)} utterances, {total / 3600:.1f} h, {len({u.speaker for u in out})} speakers")
    return out


def speaker_features(aligner, cfg, utts: list[Utterance], labels: str) -> dict[str, np.ndarray]:
    """Rows for every labelled, voiced syllable of one speaker, normalised to that speaker's baseline over all of
    their utterances (the same definition as the app, spec §2)."""
    done = []
    for u in utts:
        wav, sr = sf.read(u.wav, dtype="float32", always_2d=False)
        spans = aligner.align(wav, sr, "".join(u.chars))
        if len(spans) == len(u.chars):
            done.append((u, track_pitch(wav, sr, cfg.f0_floor, cfg.f0_ceiling), spans))
    base = baseline_of(np.concatenate([p.voiced() for _, p, _ in done])) if done else None
    X, y, ctx, contours = [], [], [], []
    for u, p, spans in done if base else []:
        norm = normalise(p.f0, base, cfg.normalise_span)
        sylls = [syllable_pitch(norm, p.t0, s.start, s.end, cfg.min_voiced_frames) for s in spans]
        F = feature_matrix(sylls)
        tones = realise(u) if labels == "canonical" else list(u.tones)
        for i, (t, s) in enumerate(zip(tones, sylls)):
            if t is None or s.contour is None:
                continue
            X.append(F[i]); y.append(t); contours.append(s.contour)
            ctx.append((tones[i - 1] if i and tones[i - 1] is not None else -1,
                        tones[i + 1] if i + 1 < len(tones) and tones[i + 1] is not None else -1))
    return {"X": np.asarray(X, np.float32).reshape(-1, N_FEATURES), "y": np.asarray(y, np.int64),
            "ctx": np.asarray(ctx, np.int64).reshape(-1, 2), "contours": np.asarray(contours, np.float32).reshape(-1, POINTS)}


def features(root: Path, utts: list[Utterance], labels: str) -> Path:
    cfg = load_settings().scoring
    out = root / f"features_v{FEATURE_VERSION}"
    out.mkdir(exist_ok=True)
    aligner = make_aligner("mms_fa", load_settings().resolved_device())
    by_spk: dict[str, list[Utterance]] = defaultdict(list)
    for u in utts:
        by_spk[u.speaker].append(u)
    for n, (spk, us) in enumerate(sorted(by_spk.items()), 1):
        f = out / f"{spk}.npz"
        if not f.exists():
            np.savez(f, **speaker_features(aligner, cfg, us, labels))
        print(f"[{n}/{len(by_spk)}] {spk}: {len(us)} utterances")
    return out


def dtw_norm(test: list[tuple[str, dict]], band: int) -> float:
    """median DTW over same-tone, same-context pairs from two different held-out speakers, / 0.1 (spec §4.4)."""
    groups: dict[tuple[int, int, int], list[tuple[str, np.ndarray]]] = defaultdict(list)
    for spk, d in test:
        for t, (p, nx), c in zip(d["y"], d["ctx"], d["contours"]):
            groups[(int(p), int(t), int(nx))].append((spk, c))
    keys = [k for k, v in groups.items() if len({s for s, _ in v}) > 1]
    rng, dists = random.Random(0), []
    for _ in range(MAX_PAIRS * 3):
        if len(dists) >= MAX_PAIRS or not keys:
            break
        g = groups[rng.choice(keys)]
        (s1, a), (s2, b) = rng.sample(g, 2)
        if s1 != s2:
            dists.append(dtw_distance(a, b, band))
    return float(np.median(dists) / 0.1)


def train(root: Path, name: str, hours: float, labels: str) -> None:
    import joblib
    import sklearn
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.metrics import confusion_matrix
    cfg = load_settings().scoring
    files = sorted((root / f"features_v{FEATURE_VERSION}").glob("*.npz"))
    spks = [f.stem for f in files]
    random.Random(0).shuffle(spks)
    test_spk = set(spks[: max(1, int(len(spks) * TEST_SHARE))])
    tr, te = [], []
    for f in files:
        d = dict(np.load(f))
        (te if f.stem in test_spk else tr).append((f.stem, d))
    Xtr = np.concatenate([d["X"] for _, d in tr]); ytr = np.concatenate([d["y"] for _, d in tr])
    Xte = np.concatenate([d["X"] for _, d in te]); yte = np.concatenate([d["y"] for _, d in te])
    clf = HistGradientBoostingClassifier(max_iter=400, learning_rate=0.1, early_stopping=True, random_state=0)
    clf.fit(Xtr, ytr)
    pred = clf.predict(Xte)
    acc = float(np.mean(pred == yte))
    per_tone = {str(t): float(np.mean(pred[yte == t] == t)) for t in TONES if np.any(yte == t)}
    meta = {"version": f"{name}-{date.today().isoformat()}", "feature_version": FEATURE_VERSION, "classes": list(TONES),
            "dtw_norm": dtw_norm(te, cfg.dtw_band), "accuracy": acc, "per_tone": per_tone,
            "confusion": confusion_matrix(yte, pred, labels=list(TONES)).tolist(),
            "n_train": int(len(ytr)), "n_test": int(len(yte)), "test_speakers": sorted(test_spk),
            "hours": hours, "labels": labels, "corpus": "AISHELL-3 (OpenSLR SLR93, Apache-2.0)",
            "sklearn": sklearn.__version__, "date": date.today().isoformat()}
    MODELS_DIR.mkdir(exist_ok=True)
    joblib.dump(clf, MODELS_DIR / f"{name}.joblib", compress=3)
    (MODELS_DIR / f"{name}.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps({k: meta[k] for k in ("accuracy", "per_tone", "dtw_norm", "n_train", "n_test")}, indent=1))
    print("ACCEPT" if acc >= 0.85 else "BELOW 0.85 — stop and decide (spec §4.4)")


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", type=Path, default=load_settings().data_dir / "corpora" / "aishell3")
    ap.add_argument("--hours", type=float, default=30.0)
    ap.add_argument("--labels", choices=["canonical", "realised"], required=True)
    ap.add_argument("--name", default="tone_v1")
    ap.add_argument("--stage", choices=["all", "features", "train"], default="all")
    a = ap.parse_args()
    if a.stage in ("all", "features"):
        download(a.root)
        features(a.root, pick(a.root, a.hours), a.labels)
    if a.stage in ("all", "train"):
        train(a.root, a.name, a.hours, a.labels)


if __name__ == "__main__":
    main()
```

Add to `Makefile` (and `tone-model rescore` to `.PHONY`):
```make
tone-model:
	cd backend && uv run python scripts/tone_model.py --labels $(LABELS)
rescore:
	cd backend && uv run python scripts/rescore.py
```

- [ ] **Step 6: Smoke-test the tool's train stage on fake features**

```bash
cd backend && mkdir -p /tmp/claude-1000/tm/features_v1 && ~/.local/bin/uv run python - <<'EOF'
import numpy as np
from shadow.scoring.features import N_FEATURES, POINTS
rng = np.random.default_rng(0)
for k in range(8):
    n = 300; y = rng.integers(0, 5, n)
    X = rng.normal(size=(n, N_FEATURES)).astype("float32"); X[:, 0] += y * 2
    np.savez(f"/tmp/claude-1000/tm/features_v1/S{k:03d}.npz", X=X, y=y, ctx=rng.integers(-1, 5, (n, 2)),
             contours=rng.normal(size=(n, POINTS)).astype("float32"))
EOF
~/.local/bin/uv run python -c "
import scripts.tone_model as t, shadow.scoring.tone as tone, pathlib
tone.MODELS_DIR = t.MODELS_DIR = pathlib.Path('/tmp/claude-1000/tm/models')
t.train(pathlib.Path('/tmp/claude-1000/tm'), 'smoke', 0.1, 'canonical')
print(tone.load_tone_model('smoke', t.MODELS_DIR).proba(__import__('numpy').zeros((1, 45))).shape)"
rm -rf /tmp/claude-1000/tm
```
Expected: an accuracy line, `ACCEPT` or `BELOW…` (either is fine for random data), then `(1, 5)`. If `import scripts.tone_model` fails because `scripts` is not a package, run it as `~/.local/bin/uv run python -c "import sys; sys.path.insert(0, 'scripts'); import tone_model as t; …"` instead.

- [ ] **Step 7: Run all backend tests and commit**

Run: `cd backend && ~/.local/bin/uv run pytest -q` (expected: all pass)
```bash
git add backend/shadow/scoring/corpus.py backend/scripts/tone_model.py backend/tests/test_corpus.py Makefile
git commit -m "feat(backend): AISHELL-3 reader and tone model training tool"
```

---

### Task 8: Train the tone model (operator task, long-running)

The controller runs this itself (not a subagent): it is a long download and GPU job. Start it as soon as Task 7 is committed and carry on with Task 9 onwards while it runs; only Task 15 needs its output.

**Files:**
- Create: `backend/shadow/scoring/models/tone_v1.joblib`, `backend/shadow/scoring/models/tone_v1.json`
- Modify: this plan's **Ledger** (bottom)

- [ ] **Step 1: Download, then decide canonical vs realised labels**

```bash
cd backend && ~/.local/bin/uv run python -c "
from shadow.config import load_settings; import scripts.tone_model as t
t.download(load_settings().data_dir / 'corpora' / 'aishell3')"
grep -rhoE "你 ni[23] 好 hao3|一 yi[124] 个 ge4|不 bu[24] 是 shi4" ../data/corpora/aishell3 --include=content.txt | sort | uniq -c
```
(run in the background; it takes as long as the 19 GB download.) If `ni2 hao3`, `yi2 ge4` or `bu2 shi4` appear, the labels are **realised**; if only `ni3 hao3`, `yi1 ge4`, `bu4 shi4` appear, they are **canonical**. Record the counts and the choice in the Ledger.

- [ ] **Step 2: Build features and train**

```bash
cd backend && ~/.local/bin/uv run python scripts/tone_model.py --labels <canonical|realised> 2>&1 | tee ../data/corpora/tone_model.log
```
Run in the background. Expected at the end: the metrics JSON and `ACCEPT`.

- [ ] **Step 3: Accept or stop**

If the last line is `BELOW 0.85 …`: **stop** and report the per-tone accuracy and confusion matrix to the user with three options — more hours (`--hours 60`, features are cached so only the new speakers' utterances are aligned), richer features (bump `FEATURE_VERSION`), or a small neural model — and wait for his choice. Do not commit the model.

If `ACCEPT`: check `ls -la backend/shadow/scoring/models/` (the joblib file should be under 20 MB; if it is larger, retrain with `max_iter=200` and note it), copy the printed metrics into the Ledger, and commit:
```bash
git add backend/shadow/scoring/models/tone_v1.joblib backend/shadow/scoring/models/tone_v1.json docs/superpowers/plans/2026-10-09-phase2-tone-scoring.md
git commit -m "feat(backend): tone model v1 trained on AISHELL-3 (metrics in the plan ledger)"
```

---

### Task 9: `score_attempt`: reference, lesson baseline, voice profile, rows

**Files:**
- Create: `backend/shadow/scoring/reference.py`, `backend/shadow/scoring/profile.py`
- Modify: `backend/shadow/scoring/__init__.py`, `backend/shadow/deps.py`, `backend/shadow/api/attempts.py:24-58`, `backend/shadow/api/lessons.py:85-92`, `backend/tests/test_attempts_api.py:22`
- Test: `backend/tests/test_scoring_api.py`

**Interfaces:**
- Consumes: `score_take`, `RefData`, `failed_result`, `TakeResult` (Task 6); `track_pitch`, `baseline_of`, `Baseline`, `Pitch` (Task 2); `ToneModel`, `FakeToneModel`, `load_tone_model` (Task 4); `VoiceProfile`, `SyllableScore` (Task 1); `audio.read_wav(path) -> (np.ndarray, int)` (existing).
- Produces:
  - `segment_syllables(seg: Segment) -> list[dict]`; `reference_spans(seg: Segment) -> list[tuple[float, float]]`; `reference_pitch(files: FileLayout, cfg: ScoringCfg, seg: Segment) -> Pitch | None`; `lesson_baseline(files: FileLayout, cfg: ScoringCfg, db: Session, lesson: Lesson) -> Baseline | None`
  - `get_profile(db) -> VoiceProfile`; `profile_baseline(p: VoiceProfile) -> Baseline | None`; `add_frames(db, p: VoiceProfile, f0_voiced: np.ndarray) -> None`; `reset_profile(db) -> None`; `MAX_FRAMES = 6000`
  - `score_attempt(deps: Deps, db: Session, segment: Segment, attempt: Attempt) -> None` (sets `attempt.score_json`, adds rows, feeds the profile; never raises; the caller commits)
  - `Deps.tone_model: ToneModel | None` (real: `load_tone_model(settings.scoring.tone_model)`; fake: `FakeToneModel()`); `loaded_models()` lists `"tone"` when present.
  - Warning codes added: `no_reference`, `score_failed`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_scoring_api.py`:
```python
import numpy as np
import soundfile as sf
from sqlmodel import Session, select
from shadow.store.models import Attempt, Segment, SyllableScore, VoiceProfile
from tests.helpers import make_tone_wav
from tests.test_lessons_api import _upload


def _post(client, path, sid):
    with open(path, "rb") as f:
        return client.post(f"/segments/{sid}/attempts", files={"audio": ("a.wav", f, "audio/wav")}, data={"mode": "echo"})


def _first_segment(client, tmp_path):
    lid = _upload(client, tmp_path)
    return lid, client.get(f"/lessons/{lid}").json()["segments"][0]


def test_a_take_is_scored_with_rows_and_feeds_the_profile(client, tmp_path):
    lid, seg = _first_segment(client, tmp_path)
    r = _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"])
    assert r.status_code == 201
    sj = r.json()["score_json"]
    assert sj["warnings"] == [] and sj["overall"] is not None and sj["model_version"] == "fake"
    n = len(sj["syllables"])
    assert n == len([s for w in seg["words_json"] for s in w["syllables"]])
    assert sj["ref_contour"]["step_ms"] == 10 and len(sj["usr_contour"]["spans"]) == n
    with Session(client.app.state.engine) as db:
        rows = db.exec(select(SyllableScore).where(SyllableScore.attempt_id == r.json()["id"])).all()
        assert len(rows) == n and {x.status for x in rows} <= {"ok", "close", "wrong", "unvoiced", "missing"}
        prof = db.exec(select(VoiceProfile)).one()
        assert prof.voiced_s > 1.0 and abs(prof.baseline_hz - 220) < 5
    assert client.get(f"/lessons/{lid}").json()["segments"][0]["last_score"] == sj["overall"]


def test_lesson_baseline_is_cached_on_the_lesson(client, tmp_path):
    from shadow.store.models import Lesson
    lid, seg = _first_segment(client, tmp_path)
    _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"])
    with Session(client.app.state.engine) as db:
        pitch = db.get(Lesson, lid).meta_json["pitch"]
        assert abs(pitch["baseline_hz"] - 220) < 5 and pitch["frames"] > 100


def test_gated_take_has_no_rows_and_null_overall(client, tmp_path):
    lid, seg = _first_segment(client, tmp_path)
    silent = tmp_path / "s.wav"
    sf.write(silent, np.zeros(16000 * 2, dtype="float32"), 16000)
    sj = _post(client, silent, seg["id"]).json()["score_json"]
    assert sj["overall"] is None and "too_quiet" in sj["warnings"]
    with Session(client.app.state.engine) as db:
        assert db.exec(select(SyllableScore)).all() == [] and db.exec(select(VoiceProfile)).all() == []


def test_null_overall_is_skipped_by_lessons_and_stats(client, tmp_path):
    lid, seg = _first_segment(client, tmp_path)
    good = _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"]).json()["score_json"]["overall"]
    silent = tmp_path / "s.wav"
    sf.write(silent, np.zeros(16000 * 2, dtype="float32"), 16000)
    _post(client, silent, seg["id"])
    out = client.get(f"/lessons/{lid}").json()["segments"][0]
    assert (out["last_score"], out["best_score"], out["attempts"]) == (good, good, 2)
    assert client.get("/stats/sentences").status_code == 200
    assert client.get(f"/lessons/{lid}/stats").status_code == 200
    assert client.get("/lessons").json()[0]["mean_last_score"] == good


def test_no_reference_alignment(client, tmp_path):
    lid, seg = _first_segment(client, tmp_path)
    with Session(client.app.state.engine) as db:
        s = db.get(Segment, seg["id"]); s.ref_alignment_json = None; db.add(s); db.commit()
    sj = _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"]).json()["score_json"]
    assert sj["warnings"] == ["no_reference"] and sj["overall"] is None


def test_a_scoring_crash_still_saves_the_take(client, tmp_path, monkeypatch):
    import shadow.scoring as scoring
    lid, seg = _first_segment(client, tmp_path)
    monkeypatch.setattr(scoring, "score_take", lambda **kw: 1 / 0)
    r = _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), seg["id"])
    assert r.status_code == 201 and r.json()["score_json"]["warnings"] == ["score_failed"]
    assert client.get(f"/attempts/{r.json()['id']}/audio").status_code == 200
    with Session(client.app.state.engine) as db:
        assert db.exec(select(Attempt)).one().score_json["overall"] is None
```

In `backend/tests/test_attempts_api.py` change line 22 from
`assert att["score_json"] is None and abs(att["duration_s"] - 1.2) < 0.05` to
`assert att["score_json"] is not None and abs(att["duration_s"] - 1.2) < 0.05`.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_scoring_api.py tests/test_attempts_api.py -q`
Expected: FAIL (`score_json` is None).

- [ ] **Step 3: Implement**

`backend/shadow/scoring/reference.py`:
```python
"""The reference side of scoring (Phase 2 spec §1 step 4, §2): cached clip pitch, spans and the lesson baseline."""
from __future__ import annotations
from pathlib import Path
import numpy as np
from sqlmodel import Session, select
from shadow.config import ScoringCfg
from shadow.ingest import audio
from shadow.scoring.pitch import Baseline, Pitch, baseline_of, track_pitch
from shadow.store.files import FileLayout
from shadow.store.models import Lesson, Segment


def segment_syllables(seg: Segment) -> list[dict]:
    return [s for w in (seg.words_json or []) for s in w.get("syllables", [])]


def reference_spans(seg: Segment) -> list[tuple[float, float]]:
    """Alignment spans are on the lesson's time axis; the clip starts at the segment's start_s."""
    return [(a["start"] - seg.start_s, a["end"] - seg.start_s) for a in (seg.ref_alignment_json or [])]


def reference_pitch(files: FileLayout, cfg: ScoringCfg, seg: Segment) -> Pitch | None:
    """The clip's pitch, cached per clip file version (an edit re-cuts the clip, so its mtime changes)."""
    if not seg.clip_wav_path or not Path(seg.clip_wav_path).exists():
        return None
    clip = Path(seg.clip_wav_path)
    cache = files.cache_dir("f0") / f"{seg.id}-{clip.stat().st_mtime_ns}.npz"
    if cache.exists():
        d = np.load(cache)
        return Pitch(float(d["t0"]), d["f0"])
    wav, sr = audio.read_wav(clip)
    p = track_pitch(wav, sr, cfg.f0_floor, cfg.f0_ceiling)
    np.savez(cache, t0=p.t0, f0=p.f0)
    return p


def lesson_baseline(files: FileLayout, cfg: ScoringCfg, db: Session, lesson: Lesson) -> Baseline | None:
    """The speaker over every clip of the lesson, computed once and kept in meta_json["pitch"] (spec §2)."""
    meta = lesson.meta_json or {}
    if "pitch" in meta:
        return Baseline(meta["pitch"]["baseline_hz"], meta["pitch"]["spread_st"])
    segs = db.exec(select(Segment).where(Segment.lesson_id == lesson.id)).all()
    voiced = [p.voiced() for p in (reference_pitch(files, cfg, s) for s in segs) if p is not None]
    allv = np.concatenate(voiced) if voiced else np.zeros(0)
    b = baseline_of(allv)
    if b is None:
        return None
    lesson.meta_json = {**meta, "pitch": {"baseline_hz": b.hz, "spread_st": b.spread_st, "frames": int(len(allv))}}
    db.add(lesson)
    return b
```

`backend/shadow/scoring/profile.py`:
```python
"""The learner's voice profile (Phase 2 spec §2): one row, the most recent voiced frames and their baseline."""
from __future__ import annotations
import numpy as np
from sqlmodel import Session, delete, select
from shadow.scoring.pitch import STEP_S, Baseline, baseline_of
from shadow.store.models import VoiceProfile, now

MAX_FRAMES = 6000                        # ≈ 60 s of voiced speech


def get_profile(db: Session) -> VoiceProfile:
    p = db.exec(select(VoiceProfile).order_by(VoiceProfile.id)).first()
    return p if p is not None else VoiceProfile()


def profile_baseline(p: VoiceProfile) -> Baseline | None:
    return Baseline(p.baseline_hz, p.spread_st) if p.baseline_hz and p.spread_st else None


def add_frames(db: Session, p: VoiceProfile, f0_voiced: np.ndarray) -> None:
    frames = (list(p.frames_json or []) + [round(float(x), 1) for x in f0_voiced])[-MAX_FRAMES:]
    b = baseline_of(np.asarray(frames))
    p.frames_json = frames
    p.baseline_hz, p.spread_st = (b.hz, b.spread_st) if b else (None, None)
    p.voiced_s = (p.voiced_s or 0.0) + len(f0_voiced) * STEP_S
    p.updated_at = now()
    db.add(p)


def reset_profile(db: Session) -> None:
    db.exec(delete(VoiceProfile))
```

`backend/shadow/scoring/__init__.py` — replace the whole file:
```python
"""Tone scoring of an attempt (Phase 2 spec §1): the database side around the pure `score_take`."""
from __future__ import annotations
import logging
from pathlib import Path
from typing import TYPE_CHECKING
from sqlmodel import Session
from shadow.ingest import audio
from shadow.scoring.profile import add_frames, get_profile, profile_baseline
from shadow.scoring.reference import lesson_baseline, reference_pitch, reference_spans, segment_syllables
from shadow.scoring.score import RefData, failed_result, score_take
from shadow.store.models import Attempt, Lesson, Segment, SyllableScore

if TYPE_CHECKING:                        # shadow.deps imports shadow.scoring.tone: avoid the cycle at runtime
    from shadow.deps import Deps

log = logging.getLogger(__name__)


def score_attempt(deps: Deps, db: Session, segment: Segment, attempt: Attempt) -> None:
    """Sets attempt.score_json, adds its SyllableScore rows and feeds the voice profile. Never raises: a failure
    leaves `overall: null` with a warning and no rows (spec §7). The caller commits."""
    cfg = deps.settings.scoring
    syllables = segment_syllables(segment)
    try:
        ref_pitch = reference_pitch(deps.files, cfg, segment)
        lesson = db.get(Lesson, segment.lesson_id)
        ref_base = lesson_baseline(deps.files, cfg, db, lesson) if ref_pitch is not None and lesson else None
        if ref_pitch is None or ref_base is None or not segment.ref_alignment_json:
            result = failed_result(syllables, ["no_reference"])
        else:
            prof = get_profile(db)
            wav, sr = audio.read_wav(Path(attempt.audio_path))
            result = score_take(ref=RefData(ref_pitch, reference_spans(segment), ref_base), syllables=syllables,
                                text=segment.text, wav=wav, sr=sr, aligner=deps.aligner, model=deps.tone_model,
                                profile=profile_baseline(prof), profile_voiced_s=prof.voiced_s or 0.0, cfg=cfg)
    except Exception:
        log.exception("scoring attempt %s failed", attempt.id)
        result = failed_result(syllables, ["score_failed"])
    attempt.score_json = result.json
    for row in result.rows:
        db.add(SyllableScore(attempt_id=attempt.id, segment_id=segment.id, **row))
    if result.rows:
        add_frames(db, get_profile(db), result.voiced_f0)
```

`backend/shadow/deps.py`:
- import `from shadow.scoring.tone import FakeToneModel, ToneModel, load_tone_model`
- add field `tone_model: ToneModel | None = None` after `downloader`
- in `loaded_models` append `"tone"` when `self.tone_model is not None`:
```python
        if self.tone_model is not None:
            out.append("tone")
        return out
```
- `build_deps(...)`: pass `tone_model=load_tone_model(settings.scoring.tone_model)`
- `fake_deps(...)`: pass `tone_model=FakeToneModel()`

`backend/shadow/api/attempts.py` — replace `att.score_json = score_attempt(deps, seg, dst)` with `score_attempt(deps, db, seg, att)` (keep the following lines; the existing `db.add(att); db.commit()` commits rows, profile and lesson baseline together).

`backend/shadow/api/lessons.py` — in `_attempt_stats`, replace `if score_json and "overall" in score_json:` with `if score_json and score_json.get("overall") is not None:`.

- [ ] **Step 4: Run all backend tests**

Run: `cd backend && ~/.local/bin/uv run pytest -q`
Expected: all pass. If an older test elsewhere asserted `score_json is None`, change it to the new behaviour and say so in the commit body.

- [ ] **Step 5: Commit**

```bash
git add backend/shadow/scoring backend/shadow/deps.py backend/shadow/api/attempts.py backend/shadow/api/lessons.py backend/tests/test_scoring_api.py backend/tests/test_attempts_api.py
git commit -m "feat(backend): score every uploaded take; lesson baseline, voice profile, syllable rows"
```

---

### Task 10: API — scored takes, tone stats, characters, voice profile, health

**Files:**
- Create: `backend/shadow/api/voice.py`
- Modify: `backend/shadow/schemas.py` (`TakeOut`), `backend/shadow/api/attempts.py` (`lesson_takes`), `backend/shadow/api/stats.py` (`syllables`, `tones`), `backend/shadow/api/health.py`, `backend/shadow/main.py:37`
- Test: `backend/tests/test_takes_api.py`, `backend/tests/test_stats_api.py`, `backend/tests/test_voice_api.py`, `backend/tests/test_health.py`

**Interfaces:**
- Consumes: `get_profile`, `reset_profile` (Task 9); `Deps.tone_model` (Task 9); `SyllableScore.target_tone` (Task 1).
- Produces (JSON):
  - `GET /lessons/{id}/takes` → each take adds `score_json: dict | null`.
  - `GET /stats/tones` → `{"tones": [{tone, mean, n}], "pairs": [{prev_tone, tone, mean, n}], "weeks": [{week: "2026-W41", tone, mean, n}]}`; tone = `coalesce(target_tone, tone)`; tones `< 0` excluded; weeks cover the last 12 ISO weeks.
  - `GET /stats/syllables` → `{"syllables": [{ch, pinyin, tone, mean, n, trend}]}` (weakest 50 by mean; `tone` = the most frequent target tone; `trend` = mean of the last 10 minus mean of the earlier ones, `null` when n < 15).
  - `GET /voice-profile` → `{baseline_hz, spread_st, voiced_s, updated_at}` (nulls and `0.0` when none); `DELETE /voice-profile` → 204.
  - `/health` adds `"tone_model": {"loaded": bool, "version": str | null, "accuracy": float | null}`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_takes_api.py`:
```python
def test_takes_carry_their_score(client, tmp_path):
    from tests.helpers import make_tone_wav
    from tests.test_lessons_api import _upload
    lid = _upload(client, tmp_path)
    sid = client.get(f"/lessons/{lid}").json()["segments"][0]["id"]
    with open(make_tone_wav(tmp_path / "t.wav", 2.6), "rb") as f:
        att = client.post(f"/segments/{sid}/attempts", files={"audio": ("t.wav", f, "audio/wav")}, data={"mode": "echo"}).json()
    take = client.get(f"/lessons/{lid}/takes").json()["takes"][0]
    assert take["score_json"] == att["score_json"]
```

Append to `backend/tests/test_stats_api.py`:
```python
def _scores(client, rows):
    """rows: (tone, target_tone, prev_tone, tone_score, ch) on one attempt each, created now."""
    from sqlmodel import Session
    from shadow.store.models import Attempt, Lesson, Segment, SyllableScore
    with Session(client.app.state.engine) as db:
        les = Lesson(title="L", source_type="upload"); db.add(les); db.commit()
        seg = Segment(lesson_id=les.id, idx=0, start_s=0, end_s=1, text="好"); db.add(seg); db.commit()
        for tone, target, prev, score, ch in rows:
            a = Attempt(segment_id=seg.id, mode="echo", audio_path="x.wav", duration_s=1.0); db.add(a); db.commit()
            db.add(SyllableScore(attempt_id=a.id, segment_id=seg.id, idx=0, ch=ch, pinyin_toneless="hao", tone=tone,
                                 target_tone=target, prev_tone=prev, tone_score=score, status="ok"))
        db.commit()


def test_tone_stats_use_target_tones_and_weeks(client):
    _scores(client, [(3, 2, 3, 0.4, "你"), (3, 3, None, 0.8, "好"), (0, None, 3, None, "吗"), (-1, None, None, None, "A")])
    out = client.get("/stats/tones").json()
    assert {t["tone"]: t["n"] for t in out["tones"]} == {2: 1, 3: 1}
    assert out["pairs"] == [{"prev_tone": 3, "tone": 2, "mean": 0.4, "n": 1}]
    assert len(out["weeks"]) == 2 and all(w["week"].count("-W") == 1 for w in out["weeks"])


def test_syllable_stats_per_character_with_trend(client):
    _scores(client, [(3, 3, None, 0.2, "好")] * 10 + [(3, 3, None, 0.8, "好")] * 10 + [(4, 4, None, 0.9, "是")])
    out = client.get("/stats/syllables").json()["syllables"]
    hao = next(s for s in out if s["ch"] == "好")
    assert hao["n"] == 20 and hao["tone"] == 3 and abs(hao["trend"] - 0.6) < 1e-9
    assert next(s for s in out if s["ch"] == "是")["trend"] is None
    assert out[0]["ch"] == "好"                              # weakest first
```

`backend/tests/test_voice_api.py`:
```python
from sqlmodel import Session
from shadow.store.models import VoiceProfile


def test_voice_profile_get_and_reset(client):
    assert client.get("/voice-profile").json() == {"baseline_hz": None, "spread_st": None, "voiced_s": 0.0, "updated_at": None}
    with Session(client.app.state.engine) as db:
        db.add(VoiceProfile(frames_json=[118.0] * 10, baseline_hz=118.0, spread_st=9.5, voiced_s=250.0)); db.commit()
    got = client.get("/voice-profile").json()
    assert (got["baseline_hz"], got["spread_st"], got["voiced_s"]) == (118.0, 9.5, 250.0) and got["updated_at"]
    assert client.delete("/voice-profile").status_code == 204
    assert client.get("/voice-profile").json()["baseline_hz"] is None
```

Append to `backend/tests/test_health.py`:
```python
def test_health_reports_the_tone_model(client):
    tm = client.get("/health").json()["tone_model"]
    assert tm == {"loaded": True, "version": "fake", "accuracy": None}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_takes_api.py tests/test_stats_api.py tests/test_voice_api.py tests/test_health.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`backend/shadow/schemas.py` — `TakeOut` gains `score_json: dict[str, Any] | None = None`. In `backend/shadow/api/attempts.py::lesson_takes`, pass `score_json=a.score_json` to `TakeOut(...)`.

`backend/shadow/api/stats.py` — replace `syllables` and `tones` with (add `from collections import Counter` and keep `defaultdict`):
```python
_TONE = func.coalesce(SyllableScore.target_tone, SyllableScore.tone)   # the tone the speaker produced, when known
_SCORED = SyllableScore.tone_score.is_not(None)


@router.get("/stats/syllables")
def syllables(db: Session = Depends(get_session)):
    """Per character, oldest first: mean, count, most frequent target tone, and the last 10 against the rest."""
    q = (select(SyllableScore.ch, SyllableScore.pinyin_toneless, _TONE, SyllableScore.tone_score)
         .where(_SCORED, _TONE >= 0).order_by(SyllableScore.attempt_id, SyllableScore.idx))
    by_ch: dict[str, dict] = {}
    for ch, pinyin, tone, score in db.exec(q).all():
        d = by_ch.setdefault(ch, {"pinyin": pinyin, "tones": Counter(), "scores": []})
        d["tones"][tone] += 1; d["scores"].append(score)
    out = []
    for ch, d in by_ch.items():
        s = d["scores"]
        trend = sum(s[-10:]) / 10 - sum(s[:-10]) / len(s[:-10]) if len(s) >= 15 else None
        out.append({"ch": ch, "pinyin": d["pinyin"], "tone": d["tones"].most_common(1)[0][0], "mean": sum(s) / len(s),
                    "n": len(s), "trend": trend})
    return {"syllables": sorted(out, key=lambda r: r["mean"])[:50]}


@router.get("/stats/tones")
def tones(db: Session = Depends(get_session)):
    q1 = select(_TONE, func.avg(SyllableScore.tone_score), func.count()).where(_SCORED, _TONE >= 0).group_by(_TONE)
    q2 = (select(SyllableScore.prev_tone, _TONE, func.avg(SyllableScore.tone_score), func.count())
          .where(_SCORED, _TONE >= 0, SyllableScore.prev_tone >= 0).group_by(SyllableScore.prev_tone, _TONE))
    since = datetime.combine(datetime.now(timezone.utc).date() - timedelta(weeks=12), datetime.min.time(), tzinfo=timezone.utc)
    q3 = (select(Attempt.created_at, _TONE, SyllableScore.tone_score).join(Attempt, Attempt.id == SyllableScore.attempt_id)
          .where(_SCORED, _TONE >= 0, Attempt.created_at >= since))
    weeks: dict[tuple[str, int], list[float]] = defaultdict(list)
    for created, tone, score in db.exec(q3).all():
        y, w, _ = created.isocalendar()
        weeks[(f"{y}-W{w:02d}", tone)].append(score)
    return {"tones": [{"tone": t, "mean": m, "n": n} for t, m, n in db.exec(q1).all()],
            "pairs": [{"prev_tone": p, "tone": t, "mean": m, "n": n} for p, t, m, n in db.exec(q2).all()],
            "weeks": [{"week": wk, "tone": t, "mean": sum(v) / len(v), "n": len(v)} for (wk, t), v in sorted(weeks.items())]}
```
(`SyllableScore.prev_tone >= 0` also drops NULLs in SQL.)

`backend/shadow/api/voice.py`:
```python
"""The learner's voice profile (Phase 2 spec §2, §6): shown in Settings, resettable."""
from fastapi import APIRouter, Depends, Response
from sqlmodel import Session, select
from shadow.scoring.profile import reset_profile
from shadow.store.db import get_session
from shadow.store.models import VoiceProfile

router = APIRouter()


@router.get("/voice-profile")
def get_voice_profile(db: Session = Depends(get_session)):
    p = db.exec(select(VoiceProfile).order_by(VoiceProfile.id)).first()
    if p is None:
        return {"baseline_hz": None, "spread_st": None, "voiced_s": 0.0, "updated_at": None}
    return {"baseline_hz": p.baseline_hz, "spread_st": p.spread_st, "voiced_s": p.voiced_s, "updated_at": p.updated_at}


@router.delete("/voice-profile", status_code=204)
def delete_voice_profile(db: Session = Depends(get_session)):
    reset_profile(db)
    db.commit()
    return Response(status_code=204)
```
Register it in `backend/shadow/main.py`: import `voice` with the other routers and add `voice.router` to the tuple on line 37.

`backend/shadow/api/health.py` — add to the returned dict:
```python
        "tone_model": _tone_model(loaded),
```
and below the route:
```python
def _tone_model(deps) -> dict:
    tm = getattr(deps, "tone_model", None) if deps else None
    meta = getattr(tm, "meta", {}) or {}
    return {"loaded": tm is not None, "version": getattr(tm, "version", None), "accuracy": meta.get("accuracy")}
```

- [ ] **Step 4: Run all backend tests**

Run: `cd backend && ~/.local/bin/uv run pytest -q`
Expected: all pass. If an existing stats test asserted the old `/stats/syllables` shape (`pinyin`, `tone`, `mean`, `n` grouped by pinyin), update it to the per-character shape.

- [ ] **Step 5: Commit**

```bash
git add backend/shadow/schemas.py backend/shadow/api backend/shadow/main.py backend/tests
git commit -m "feat(backend): scored takes, tone and character stats, voice profile and tone model health"
```

---

### Task 11: Frontend — score types, scored cells and the score header

**Files:**
- Create: `frontend/src/lib/score.ts`, `frontend/src/lib/score.test.ts`, `frontend/src/components/ScoreHeader.tsx`, `frontend/src/components/ScoreHeader.test.tsx`, `frontend/src/components/CellRow.test.tsx`
- Modify: `frontend/src/api/types.ts`, `frontend/src/lib/cells.ts`, `frontend/src/lib/cells.test.ts`, `frontend/src/components/CellRow.tsx`, `frontend/src/components/TwoTrack.tsx`, `frontend/src/index.css`

**Interfaces:**
- Consumes: the score JSON of Task 6 (`Attempt.score_json`, `Take.score_json`).
- Produces:
  - types: `SylStatus`, `Contour`, `ScoredSyllable`, `Score`; `Attempt.score_json: Score | null`; `Take.score_json?: Score | null`
  - `cells.ts`: `CellStatus = 'ok' | 'close' | 'wrong' | 'suspect' | 'missing' | 'unvoiced' | 'neutral'`; `Cell` gains `target?: number | null; heard?: number | null`; `cellStatusFromScore` is removed
  - `score.ts`: `withScore(cells: Cell[], score: Score | null | undefined): Cell[]`, `warningText(score: Score | null | undefined): string | null`, `pct(x: number | null | undefined): string`, `cellTitle(c: Cell): string`, `TONE_NAMES`
  - `<ScoreHeader score={Score | null | undefined} best={number | null} attempts={number} />`
  - `TwoTrack` prop `score?: Score | null` (the You row's cells come from `withScore`)

- [ ] **Step 1: Types**

In `frontend/src/api/types.ts` add, and change `Attempt.score_json` to `Score | null` and add `score_json?: Score | null` to `Take`:
```ts
// Phase 2 score JSON (spec §5.1). `overall` is null when the take was not scored; `warnings` then says why.
export type SylStatus = 'ok' | 'close' | 'wrong' | 'unvoiced' | 'missing'
export interface Contour { t0_s: number; step_ms: number; f0_st: (number | null)[]; spans: [number, number][] }
export interface ScoredSyllable {
  ch: string; pinyin: string; tone: number; target_tone: number | null; heard_tone: number | null; status: SylStatus
  tone_score: number | null; p_target: number | null; contour: number | null
}
export interface Score {
  overall: number | null; tone_overall: number | null; segmental_overall: number | null; rate_ratio: number | null
  ref_contour: Contour | null; usr_contour: Contour | null; syllables: ScoredSyllable[]; warnings: string[]
}
```

- [ ] **Step 2: Write the failing tests**

`frontend/src/lib/score.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import type { Score, ScoredSyllable } from '../api/types'
import type { Cell } from './cells'
import { cellTitle, pct, warningText, withScore } from './score'

const cells: Cell[] = [{ ch: '你', pinyin: 'ní', tone: 3, status: 'neutral' }, { ch: '好', pinyin: 'hǎo', tone: 3, status: 'neutral' }]
const syl = (o: Partial<ScoredSyllable>): ScoredSyllable => ({ ch: '你', pinyin: 'ní', tone: 3, target_tone: 2, heard_tone: 2, status: 'ok', tone_score: 0.9, p_target: 0.9, contour: 0.9, ...o })
const score = (o: Partial<Score> = {}): Score => ({ overall: 0.7, tone_overall: 0.7, segmental_overall: null, rate_ratio: 1, ref_contour: null, usr_contour: null,
  syllables: [syl({}), syl({ ch: '好', target_tone: 3, heard_tone: 2, status: 'wrong', tone_score: 0.3 })], warnings: [], ...o })

describe('score', () => {
  it('puts each syllable verdict on its cell', () => {
    const out = withScore(cells, score())
    expect(out.map((c) => c.status)).toEqual(['ok', 'wrong'])
    expect(out[1]).toMatchObject({ score: 0.3, target: 3, heard: 2 })
  })
  it('leaves cells alone without a score or when the counts differ', () => {
    expect(withScore(cells, null)).toBe(cells)
    expect(withScore(cells, score({ syllables: [syl({})] }))).toBe(cells)
  })
  it('explains a gated take', () => {
    expect(warningText(score({ overall: null, warnings: ['too_quiet'] }))).toBe('Too quiet — not scored. Move closer to the mic.')
    expect(warningText(score({ overall: null, warnings: ['odd_code'] }))).toBe('Not scored (odd_code).')
    expect(warningText(score())).toBeNull()
  })
  it('formats percentages and cell titles', () => {
    expect(pct(0.456)).toBe('46'); expect(pct(null)).toBe('—')
    expect(cellTitle({ ...cells[1], status: 'wrong', score: 0.41, target: 3, heard: 2 })).toBe('hǎo · Speaker: tone 3 (low) · You: tone 2 (rising) · 41')
    expect(cellTitle(cells[0])).toBe('ní')
  })
})
```

`frontend/src/components/CellRow.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import CellRow from './CellRow'

describe('<CellRow>', () => {
  it('shows score, target→heard on a wrong tone, ∅ unvoiced and – missing', () => {
    render(<CellRow variant="you" cells={[
      { ch: '你', pinyin: 'ní', tone: 3, status: 'ok', score: 0.92, target: 2, heard: 2 },
      { ch: '好', pinyin: 'hǎo', tone: 3, status: 'wrong', score: 0.31, target: 3, heard: 2 },
      { ch: '吗', pinyin: 'ma', tone: 0, status: 'unvoiced', score: null },
      { ch: '呢', pinyin: 'ne', tone: 0, status: 'missing', score: 0 },
    ]} />)
    const [ok, wrong, unvoiced, missing] = screen.getAllByRole('button')
    expect(ok).toHaveClass('cell-ok'); expect(ok).toHaveTextContent('92')
    expect(wrong).toHaveClass('cell-bad'); expect(wrong).toHaveTextContent('3→2')
    expect(unvoiced).toHaveClass('cell-unvoiced'); expect(unvoiced).toHaveTextContent('∅')
    expect(missing).toHaveClass('cell-missing'); expect(missing).toHaveTextContent('–')
    expect(wrong).toHaveAttribute('title', 'hǎo · Speaker: tone 3 (low) · You: tone 2 (rising) · 31')
  })
})
```

`frontend/src/components/ScoreHeader.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Score } from '../api/types'
import ScoreHeader from './ScoreHeader'

const s = (o: Partial<Score>): Score => ({ overall: 0.82, tone_overall: 0.82, segmental_overall: null, rate_ratio: 1.1, ref_contour: null, usr_contour: null, syllables: [], warnings: [], ...o })

describe('<ScoreHeader>', () => {
  it('shows overall, tone, segmental placeholder, best and attempts', () => {
    render(<ScoreHeader score={s({})} best={0.9} attempts={3} />)
    expect(screen.getByTestId('overall')).toHaveTextContent('82')
    expect(screen.getByText('tone 82')).toBeInTheDocument()
    expect(screen.getByText('segmental · Phase 3')).toBeInTheDocument()
    expect(screen.getByText('best 90')).toBeInTheDocument()
    expect(screen.getByText('3 attempts')).toBeInTheDocument()
  })
  it('shows the gate warning instead of a score', () => {
    render(<ScoreHeader score={s({ overall: null, tone_overall: null, warnings: ['too_short'] })} best={null} attempts={1} />)
    expect(screen.getByText(/Too short — not scored/)).toBeInTheDocument()
    expect(screen.queryByTestId('overall')).toBeNull()
  })
  it('says nothing is scored yet without a take', () => {
    render(<ScoreHeader score={undefined} best={null} attempts={0} />)
    expect(screen.getByText('no score yet')).toBeInTheDocument()
  })
})
```

In `frontend/src/lib/cells.test.ts`, replace the `cellStatusFromScore` import and its test (line 42) with:
```ts
    expect(cellClass({ ch: 'x', pinyin: '', tone: 1, status: 'close' })).toBe('cell-warn')
    expect(cellClass({ ch: 'x', pinyin: '', tone: 1, status: 'wrong' })).toBe('cell-bad')
    expect(cellClass({ ch: 'x', pinyin: '', tone: 1, status: 'missing' })).toBe('cell-missing')
```

- [ ] **Step 3: Run to verify failure**

Run: `cd frontend && npm test -- --run src/lib src/components/CellRow.test.tsx src/components/ScoreHeader.test.tsx`
Expected: FAIL (modules / exports missing).

- [ ] **Step 4: Implement**

`frontend/src/lib/cells.ts` — replace the `CellStatus`/`Cell` lines, delete `cellStatusFromScore`, and replace `cellClass`:
```ts
export type CellStatus = 'ok' | 'close' | 'wrong' | 'suspect' | 'missing' | 'unvoiced' | 'neutral'
export interface Cell { ch: string; pinyin: string; tone: number; score?: number | null; status?: CellStatus; target?: number | null; heard?: number | null }
```
```ts
// Phase 2 spec §3: green ok, orange close, red a different tone heard, grey unvoiced, dashed outline missing.
export function cellClass(c: Cell): string {
  return { ok: 'cell-ok', close: 'cell-warn', wrong: 'cell-bad', suspect: 'cell-warn', missing: 'cell-missing', unvoiced: 'cell-unvoiced', neutral: 'cell-neutral' }[c.status ?? 'neutral']
}
```

`frontend/src/index.css` — after `.cell-neutral`:
```css
.cell-missing { @apply bg-transparent border-dashed border-fgdim; }
```

`frontend/src/lib/score.ts`:
```ts
import type { Score } from '../api/types'
import type { Cell } from './cells'

export const TONE_NAMES: Record<number, string> = { 0: 'neutral', 1: 'high', 2: 'rising', 3: 'low', 4: 'falling' }
const WARNINGS: Record<string, string> = {
  too_short: 'Too short — not scored. Say the whole sentence.',
  too_quiet: 'Too quiet — not scored. Move closer to the mic.',
  clipped: 'Too loud — not scored. Lower the mic gain.',
  wrong_or_unclear: 'Could not match this to the sentence — not scored.',
  no_voice: 'No voice found — not scored.',
  no_tone_model: 'Tone model missing — not scored. See docs/running.md.',
  no_reference: 'This sentence has no reference timing — not scored.',
  align_failed: 'Could not align this take — not scored.',
  score_failed: 'Scoring failed — the take is saved.',
}

// The You row's cells with each syllable's verdict; unchanged when there is no score or it is for other text.
export function withScore(cells: Cell[], score: Score | null | undefined): Cell[] {
  const syl = score?.syllables
  if (!syl?.length || syl.length !== cells.length) return cells
  return cells.map((c, i) => ({ ...c, status: syl[i].status, score: syl[i].tone_score, target: syl[i].target_tone, heard: syl[i].heard_tone }))
}

export function warningText(score: Score | null | undefined): string | null {
  const w = score?.overall == null ? score?.warnings?.[0] : undefined
  return w ? WARNINGS[w] ?? `Not scored (${w}).` : null
}

export const pct = (x: number | null | undefined): string => (x == null ? '—' : String(Math.round(x * 100)))

export function cellTitle(c: Cell): string {
  if (c.target == null || c.heard == null) return c.pinyin
  return `${c.pinyin} · Speaker: tone ${c.target} (${TONE_NAMES[c.target]}) · You: tone ${c.heard} (${TONE_NAMES[c.heard]}) · ${pct(c.score)}`
}
```

`frontend/src/components/CellRow.tsx` — replace the file:
```tsx
import { cellClass, type Cell } from '../lib/cells'
import { cellTitle, pct } from '../lib/score'

function youMark(c: Cell): string {
  if (c.status === 'unvoiced') return '∅'
  if (c.status === 'missing' || c.score == null) return '–'
  return pct(c.score)
}
export default function CellRow({ cells, variant, onCellClick }: { cells: Cell[]; variant: 'ref' | 'you'; onCellClick?: (i: number) => void }) {
  return (
    <div className="flex flex-wrap gap-1 mt-2 justify-center">
      {cells.map((c, i) => (
        <button key={i} title={variant === 'you' ? cellTitle(c) : c.pinyin} onClick={() => onCellClick?.(i)}
          className={`w-10 max-w-[56px] rounded border px-1 py-1 text-center ${cellClass(c)}`}>
          <span className="block font-hanzi text-fghi text-sm leading-tight">{c.ch}</span>
          <span className="block text-[10px] text-ref">{variant === 'ref' ? `${c.pinyin} ${c.tone >= 0 ? c.tone : ''}`
            : c.status === 'wrong' && c.target != null && c.heard != null ? `${c.target}→${c.heard}` : `${c.tone >= 0 ? c.tone : ''}`}</span>
          {variant === 'you' && <span className="block text-[9px] text-fgdim">{youMark(c)}</span>}
        </button>))}
    </div>
  )
}
```

`frontend/src/components/ScoreHeader.tsx`:
```tsx
import type { Score } from '../api/types'
import { pct, warningText } from '../lib/score'

// The You track's header (main spec §7.2): overall large, then tone, segmental (Phase 3), best so far, attempts.
export default function ScoreHeader({ score, best, attempts }: { score: Score | null | undefined; best: number | null; attempts: number }) {
  const chip = 'normal-case tracking-normal rounded bg-panel2 px-1.5 py-0.5 text-fgdim'
  if (!score) return <span className="normal-case tracking-normal text-fgdim">no score yet</span>
  const warning = warningText(score)
  if (warning) return <span className="normal-case tracking-normal text-warn">{warning}</span>
  return (
    <span className="flex items-center gap-1.5">
      <span data-testid="overall" className="text-lg text-fghi normal-case tracking-normal">{pct(score.overall)}</span>
      <span className={chip}>tone {pct(score.tone_overall)}</span>
      <span className={chip}>segmental · Phase 3</span>
      {best != null && <span className={chip}>best {pct(best)}</span>}
      <span className={chip}>{attempts} attempt{attempts === 1 ? '' : 's'}</span>
    </span>
  )
}
```

`frontend/src/components/TwoTrack.tsx`:
- import `type { Score }` from `'../api/types'` and `withScore` from `'../lib/score'`
- add `score?: Score | null` to `Props`
- after `const cells = …` add `const youCells = useMemo(() => withScore(cells, p.score), [cells, p.score])`
- the You row uses `<CellRow cells={youCells} variant="you" />`
- replace `{p.scoreHeader ?? <span className="normal-case tracking-normal text-fgdim">score arrives in Phase 2</span>}` with `{p.scoreHeader}`

- [ ] **Step 5: Run the frontend checks**

Run: `cd frontend && npm test -- --run && npx eslint . && npx tsc -b`
Expected: all pass (fix any other import of `cellStatusFromScore` the compiler finds).

- [ ] **Step 6: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): scored cells (ok, close, wrong with heard tone, unvoiced, missing) and the score header"
```

---

### Task 12: Frontend — pitch lines

**Files:**
- Create: `frontend/src/lib/pitch.ts`, `frontend/src/lib/pitch.test.ts`, `frontend/src/components/PitchLine.tsx`
- Modify: `frontend/src/components/TwoTrack.tsx`

**Interfaces:**
- Consumes: `Contour`, `Score` (Task 11).
- Produces:
  - `type Pt = [number, number | null]` (time s, normalised pitch or null)
  - `contourPoints(c: Contour): Pt[]`
  - `warpPoints(ref: Contour, targetSpans: [number, number][]): Pt[]` — each reference syllable's frames mapped linearly onto the learner's span of the same syllable, a `null` break between syllables
  - `pitchRange(...series: Pt[][]): [number, number]` — finite min/max padded by 10 %, at least 2 units wide
  - `pathOf(points: Pt[], pxPerSec: number, height: number, range: [number, number]): string` — SVG path `M…L…`, a new `M` after every null
  - `<PitchLine series={{ points: Pt[]; className: string }[]} pxPerSec={number} duration={number} height={number} range={[number, number]} />` — an absolutely positioned SVG over the waveform

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/pitch.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import type { Contour } from '../api/types'
import { contourPoints, pathOf, pitchRange, warpPoints } from './pitch'

const c: Contour = { t0_s: 0.1, step_ms: 10, f0_st: [0, 1, null, 2], spans: [[0.1, 0.12], [0.12, 0.14]] }

describe('pitch', () => {
  it('turns a contour into timed points', () => {
    expect(contourPoints(c)).toEqual([[0.1, 0], [0.11, 1], [0.12, null], [0.13, 2]].map(([t, v]) => [expect.closeTo(t as number, 9), v]))
  })
  it('warps each reference syllable onto the learner span, breaking between syllables', () => {
    const pts = warpPoints(c, [[1.0, 1.4], [1.4, 2.0]])
    expect(pts[0][0]).toBeCloseTo(1.0); expect(pts[0][1]).toBe(0)
    expect(pts[1][0]).toBeCloseTo(1.2); expect(pts[1][1]).toBe(1)
    expect(pts[2][1]).toBeNull()                                  // syllable break
    expect(pts.at(-1)![0]).toBeCloseTo(1.4 + 0.3)                  // frame 0.13 is halfway through the second span
  })
  it('range is padded and never collapses', () => {
    expect(pitchRange([[0, 1], [1, 1]])).toEqual([0, 2])
    const [lo, hi] = pitchRange([[0, -2], [1, 3]], [[0, null]])
    expect(lo).toBeCloseTo(-2.5); expect(hi).toBeCloseTo(3.5)
  })
  it('path breaks at nulls and maps higher pitch up', () => {
    const d = pathOf([[0, 0], [1, 2], [2, null], [3, 0]], 10, 40, [0, 2])
    expect(d).toBe('M0.0,40.0L10.0,0.0M30.0,40.0')
  })
})
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- --run src/lib/pitch.test.ts`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

`frontend/src/lib/pitch.ts`:
```ts
import type { Contour } from '../api/types'

// A pitch point: time (s) on the track's own axis and normalised pitch (spec §5.1), null where unvoiced.
export type Pt = [number, number | null]

export function contourPoints(c: Contour): Pt[] {
  return c.f0_st.map((v, i) => [c.t0_s + (i * c.step_ms) / 1000, v])
}

// The reference curve drawn faintly behind yours (spec §6): each reference syllable's frames are stretched onto your
// span of the same syllable, so the two curves line up syllable by syllable even when your timing differs.
export function warpPoints(ref: Contour, targetSpans: [number, number][]): Pt[] {
  const pts = contourPoints(ref), out: Pt[] = []
  ref.spans.forEach(([rs, re], i) => {
    const target = targetSpans[i]
    if (!target || re <= rs) return
    const [ts, te] = target
    if (out.length) out.push([ts, null])
    for (const [t, v] of pts) if (t >= rs && t <= re) out.push([ts + ((t - rs) / (re - rs)) * (te - ts), v])
  })
  return out
}

export function pitchRange(...series: Pt[][]): [number, number] {
  const vals = series.flat().map(([, v]) => v).filter((v): v is number => v != null && Number.isFinite(v))
  if (!vals.length) return [-1, 1]
  let lo = Math.min(...vals), hi = Math.max(...vals)
  if (hi - lo < 2) { const m = (hi + lo) / 2; lo = m - 1; hi = m + 1; return [lo, hi] }
  const pad = (hi - lo) * 0.1
  return [lo - pad, hi + pad]
}

export function pathOf(points: Pt[], pxPerSec: number, height: number, [lo, hi]: [number, number]): string {
  let d = '', pen = false
  for (const [t, v] of points) {
    if (v == null) { pen = false; continue }
    const x = (t * pxPerSec).toFixed(1), y = (height - ((v - lo) / (hi - lo)) * height).toFixed(1)
    d += `${pen ? 'L' : 'M'}${x},${y}`; pen = true
  }
  return d
}
```
(The `pitchRange` test's first case: values 1 and 1 → width 0 → `[0, 2]`.)

`frontend/src/components/PitchLine.tsx`:
```tsx
import { pathOf, type Pt } from '../lib/pitch'

interface Props { series: { points: Pt[]; className: string }[]; pxPerSec: number; duration: number; height: number; range: [number, number] }
export default function PitchLine({ series, pxPerSec, duration, height, range }: Props) {
  const width = Math.max(1, Math.round(duration * pxPerSec))
  return (
    <svg data-testid="pitch-line" className="absolute left-0 top-0 pointer-events-none" width={width} height={height} aria-hidden>
      {series.map((s, i) => <path key={i} d={pathOf(s.points, pxPerSec, height, range)} className={s.className} fill="none" strokeWidth={2} strokeLinecap="round" />)}
    </svg>
  )
}
```

`frontend/src/components/TwoTrack.tsx`:
- import `PitchLine` and `{ contourPoints, pitchRange, warpPoints }` from `'../lib/pitch'`
- compute:
```tsx
  const sc = p.score
  const refPts = useMemo(() => (sc?.ref_contour ? contourPoints(sc.ref_contour) : []), [sc])
  const usrPts = useMemo(() => (sc?.usr_contour ? contourPoints(sc.usr_contour) : []), [sc])
  const ghost = useMemo(() => (sc?.ref_contour && sc.usr_contour ? warpPoints(sc.ref_contour, sc.usr_contour.spans) : []), [sc])
  const range = useMemo(() => pitchRange(refPts, usrPts), [refPts, usrPts])
```
- wrap each `<Waveform …/>` in `<div className="relative inline-block">…</div>` and add after it, for the reference: `{refPts.length > 0 && <PitchLine series={[{ points: refPts, className: 'stroke-ref' }]} pxPerSec={pxPerSec} duration={p.refDuration} height={44} range={range} />}`; for the You track: `{usrPts.length > 0 && <PitchLine series={[{ points: ghost, className: 'stroke-ref opacity-30' }, { points: usrPts, className: 'stroke-warn' }]} pxPerSec={pxPerSec} duration={p.youDuration} height={44} range={range} />}`
- If `stroke-ref`/`stroke-warn` are not generated (check `tailwind.config` for the `ref` and `warn` colours; Tailwind generates `stroke-*` for theme colours), use the hex of those colours in a `stroke` attribute instead of a class.

Add to `frontend/src/lib/pitch.test.ts` a render check:
```tsx
import { render } from '@testing-library/react'
import PitchLine from '../components/PitchLine'
it('PitchLine draws one path per series', () => {
  const { container } = render(<PitchLine series={[{ points: [[0, 0], [1, 1]], className: 'a' }, { points: [], className: 'b' }]} pxPerSec={10} duration={1} height={44} range={[0, 1]} />)
  expect(container.querySelectorAll('path')).toHaveLength(2)
})
```
(rename the file to `pitch.test.tsx` for JSX.)

- [ ] **Step 4: Run the frontend checks**

Run: `cd frontend && npm test -- --run && npx eslint . && npx tsc -b`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): pitch lines over both tracks, the reference warped behind yours"
```

---

### Task 13: Frontend — scores flow through Practice, stored takes and Flow

**Files:**
- Modify: `frontend/src/store/practice.ts`, `frontend/src/pages/Practice.tsx` (`stored`, `loadTakes`, `finishRecording`, `<TwoTrack>` props), `frontend/src/pages/useFlow.ts:99-112`, `frontend/src/lib/score.ts`
- Test: `frontend/src/lib/score.test.ts`, `frontend/src/pages/Practice.test.tsx`, `frontend/src/store/practice.test.ts`

**Interfaces:**
- Consumes: `Score`, `withScore`, `warningText` (Task 11); `ScoreHeader` (Task 11); `TwoTrack.score` (Tasks 11–12).
- Produces:
  - `LastAttempt` and `StoredTake` gain `score?: Score | null`
  - `applyAttempt(seg: Segment, overall: number | null | undefined): Segment` in `lib/score.ts` (attempts + 1; `last_score` = overall when not null; `best_score` = max)
  - Practice passes `score={take?.score}` and `scoreHeader={<ScoreHeader score={take?.score} best={seg.best_score} attempts={seg.attempts} />}` to `TwoTrack`; a gated take sets the hint line to `warningText(score)`.

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/lib/score.test.ts`:
```ts
import type { Segment } from '../api/types'
import { applyAttempt } from './score'
describe('applyAttempt', () => {
  const s = { id: 1, last_score: 0.5, best_score: 0.6, attempts: 2 } as Segment
  it('counts the attempt and moves last and best', () => {
    expect(applyAttempt(s, 0.8)).toMatchObject({ attempts: 3, last_score: 0.8, best_score: 0.8 })
    expect(applyAttempt(s, 0.4)).toMatchObject({ attempts: 3, last_score: 0.4, best_score: 0.6 })
  })
  it('an unscored take only counts', () => {
    expect(applyAttempt(s, null)).toMatchObject({ attempts: 3, last_score: 0.5, best_score: 0.6 })
  })
})
```

In `frontend/src/pages/Practice.test.tsx`, add `score?: unknown` to the `twoTrack` type in `h` (`twoTrack: null as null | { …; score?: unknown }`) and add inside `describe('<Practice>')`:
```tsx
  it('Echo: the uploaded take’s score reaches the You track and the sentence’s last score', async () => {
    const score = { overall: 0.8, tone_overall: 0.8, segmental_overall: null, rate_ratio: 1, ref_contour: null, usr_contour: null, syllables: [], warnings: [] }
    h.api.segments.postAttempt.mockResolvedValue({ id: 99, score_json: score })
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    await waitFor(() => expect(usePractice.getState().sessionId).toBe(5))
    press('Enter'); await screen.findByRole('button', { name: '■ stop' }); await flush()
    press('Enter'); await flush()
    await waitFor(() => expect(h.twoTrack?.score).toEqual(score))
    expect(usePractice.getState().lesson!.segments[0]).toMatchObject({ last_score: 0.8, attempts: 1 })
  })

  it('a gated take explains itself in the hint line', async () => {
    const score = { overall: null, tone_overall: null, segmental_overall: null, rate_ratio: null, ref_contour: null, usr_contour: null, syllables: [], warnings: ['too_quiet'] }
    h.api.segments.postAttempt.mockResolvedValue({ id: 99, score_json: score })
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('Enter'); await screen.findByRole('button', { name: '■ stop' }); await flush()
    press('Enter'); await flush()
    expect(await screen.findByText('Too quiet — not scored. Move closer to the mic.')).toBeInTheDocument()
  })

  it('stored takes bring their score back when the lesson is reopened', async () => {
    const score = { overall: 0.6, tone_overall: 0.6, segmental_overall: null, rate_ratio: 1, ref_contour: null, usr_contour: null, syllables: [], warnings: [] }
    h.api.lessons.takes.mockResolvedValue([{ segment_id: 11, attempt_id: 7, mode: 'echo', created_at: '', duration_s: 1, score_json: score }])
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    await waitFor(() => expect(h.twoTrack?.score).toEqual(score))
  })
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- --run src/lib/score.test.ts src/pages/Practice.test.tsx`
Expected: FAIL (`applyAttempt` missing; `score` undefined on TwoTrack).

- [ ] **Step 3: Implement**

`frontend/src/lib/score.ts` — add (import `Segment` type):
```ts
// The sentence after one more attempt, as the lessons API would now report it (last/best of scored takes only).
export function applyAttempt(seg: Segment, overall: number | null | undefined): Segment {
  if (overall == null) return { ...seg, attempts: seg.attempts + 1 }
  return { ...seg, attempts: seg.attempts + 1, last_score: overall, best_score: Math.max(seg.best_score ?? overall, overall) }
}
```

`frontend/src/store/practice.ts` — import `Score` and add `score?: Score | null` to both `LastAttempt` and `StoredTake`.

`frontend/src/pages/Practice.tsx`:
- `const stored = (attemptId: number, duration: number, score?: Score | null): StoredTake => ({ id: attemptId, url: api.attempts.audioUrl(attemptId), duration, score })`
- in the takes loader: `stored(t.attempt_id, t.duration_s, t.score_json)`
- in `finishRecording`, replace the `uploaded` helper and the `.then` of `upload` with:
```tsx
    // Once uploaded, the take is the sentence's newest stored one, with its score (spec §6).
    const uploaded = (a: Attempt) => {
      const cur = usePractice.getState()
      cur.markPractised(s.id); cur.recordTake(s.id, stored(a.id, duration, a.score_json))
      const now = cur.lesson?.segments.find((x) => x.id === s.id)
      if (now) cur.updateSegment(applyAttempt(now, a.score_json?.overall))
      const why = warningText(a.score_json)
      if (why) cur.setHint(why)
    }
```
```tsx
      .then((a) => { uploaded(a); const cur = usePractice.getState(); if (cur.lastAttempt?.url === url) cur.setLastAttempt({ ...take, id: a.id, score: a.score_json }) })
```
- the `<TwoTrack …>` call gains `score={take?.score ?? null}` and `scoreHeader={<ScoreHeader score={take?.score} best={seg.best_score} attempts={seg.attempts} />}` (import `ScoreHeader`, `applyAttempt`, `warningText`, and the `Score` type).

`frontend/src/pages/useFlow.ts` — inside the upload loop, after `attemptId = (await api.segments.postAttempt(…)).id`, keep the attempt and update the sentence so its row takes its colour as soon as the slice is scored:
```ts
        const a = await api.segments.postAttempt(t.rg.segmentId, t.wav, { session_id, mode: 'flow' })
        attemptId = a.id
        const ps = usePractice.getState()
        ps.markPractised(t.rg.segmentId)
        ps.recordTake(t.rg.segmentId, { id: attemptId, url: api.attempts.audioUrl(attemptId), duration: t.samples.length / sr, score: a.score_json })
        const now = ps.lesson?.segments.find((x) => x.id === t.rg.segmentId)
        if (now) ps.updateSegment(applyAttempt(now, a.score_json?.overall))
```
(The lesson reload after the loop stays; it reconciles with the server.)

- [ ] **Step 4: Run the frontend checks**

Run: `cd frontend && npm test -- --run && npx eslint . && npx tsc -b`
Expected: all pass. Existing tests that mock `postAttempt` with `{ id: 99 }` keep working because `score_json` is then undefined and `applyAttempt` only counts.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): scores reach the feedback block, stored takes, the drawer and Flow rows"
```

---

### Task 14: Frontend — Stats (tone trend, tone-pair matrix, characters) and the voice profile

Load the `dataviz` skill before writing the chart and the matrix.

**Files:**
- Create: `frontend/src/components/ToneTrend.tsx`, `frontend/src/components/ToneMatrix.tsx`, `frontend/src/components/ToneMatrix.test.tsx`, `frontend/src/pages/Stats.test.tsx`
- Modify: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`, `frontend/src/pages/Stats.tsx`, `frontend/src/pages/Settings.tsx`, `frontend/src/pages/Settings.test.tsx`

**Interfaces:**
- Consumes: Task 10 endpoints.
- Produces:
  - types: `ToneStats` gains `weeks: { week: string; tone: number; mean: number; n: number }[]`; `SyllableStats = { syllables: { ch: string; pinyin: string; tone: number; mean: number; n: number; trend: number | null }[] }`; `VoiceProfile = { baseline_hz: number | null; spread_st: number | null; voiced_s: number; updated_at: string | null }`
  - client: `api.voiceProfile.get(): Promise<VoiceProfile>`, `api.voiceProfile.reset(): Promise<void>`
  - `<ToneMatrix pairs={ToneStats['pairs']} />` (5×5, rows previous tone 0–4, columns tone 0–4; cell text = mean ×100, `title` "after tone P, tone T: M (n N)"; `opacity-40` when n < 5; class by mean: ≥ 0.7 `cell-ok`, ≥ 0.5 `cell-warn`, else `cell-bad`; empty cells `cell-neutral` with "·")
  - `<ToneTrend weeks={ToneStats['weeks']} />` (one line per tone over the weeks, 0–100 axis, legend with tone names)

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/ToneMatrix.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ToneMatrix from './ToneMatrix'

describe('<ToneMatrix>', () => {
  it('lays pairs out previous tone × tone, dims thin cells', () => {
    render(<ToneMatrix pairs={[{ prev_tone: 3, tone: 2, mean: 0.42, n: 3 }, { prev_tone: 1, tone: 4, mean: 0.9, n: 12 }]} />)
    const thin = screen.getByTitle('after tone 3, tone 2: 42 (n 3)')
    expect(thin).toHaveTextContent('42'); expect(thin).toHaveClass('cell-bad'); expect(thin).toHaveClass('opacity-40')
    expect(screen.getByTitle('after tone 1, tone 4: 90 (n 12)')).toHaveClass('cell-ok')
    expect(screen.getAllByText('·')).toHaveLength(23)
  })
})
```

`frontend/src/pages/Stats.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

const h = vi.hoisted(() => ({ stats: {
  activity: vi.fn(() => Promise.resolve({ days: [] })), sentences: vi.fn(() => Promise.resolve({ regressed: [], by_last: [] })),
  syllables: vi.fn(() => Promise.resolve({ syllables: [{ ch: '好', pinyin: 'hao', tone: 3, mean: 0.5, n: 20, trend: 0.2 }] })),
  tones: vi.fn(() => Promise.resolve({ tones: [{ tone: 3, mean: 0.55, n: 20 }], pairs: [{ prev_tone: 3, tone: 3, mean: 0.4, n: 6 }], weeks: [{ week: '2026-W41', tone: 3, mean: 0.55, n: 20 }] })),
} }))
vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api/client')>()), api: { stats: h.stats } }))
import Stats from './Stats'

describe('<Stats>', () => {
  it('shows characters with trend, tone means, the trend chart and the pair matrix', async () => {
    render(<MemoryRouter><Stats /></MemoryRouter>)
    expect(await screen.findByText('好')).toBeInTheDocument()
    expect(screen.getByText('↑ 20')).toBeInTheDocument()
    expect(screen.getByText(/Tone 3 \(low\)/)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /Tone scores per week/ })).toBeInTheDocument()
    expect(screen.getByTitle('after tone 3, tone 3: 40 (n 6)')).toBeInTheDocument()
  })
})
```
(If `Shell` needs more of `api` than `stats`, add the missing members to the mock as `vi.fn()` resolving to empty values.)

Append to `frontend/src/pages/Settings.test.tsx` (extend the hoisted object with `voice: { get: vi.fn(), reset: vi.fn() }`, mock `../api/client` with `api: { voiceProfile: h.voice }` merged into the original, and add a `beforeEach(() => h.voice.get.mockResolvedValue({ baseline_hz: null, spread_st: null, voiced_s: 0, updated_at: null }))` so the existing Settings tests, which now fetch the profile on mount, keep working):
```tsx
  it('shows the voice profile and resets it after confirming', async () => {
    h.voice.get.mockResolvedValue({ baseline_hz: 118.2, spread_st: 9.46, voiced_s: 252, updated_at: '2026-10-09T10:00:00Z' })
    h.voice.reset.mockResolvedValue(undefined)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<Settings />)
    expect(await screen.findByText('Your baseline: 118 Hz · range 9.5 st · from 4.2 min of speech')).toBeInTheDocument()
    h.voice.get.mockResolvedValue({ baseline_hz: null, spread_st: null, voiced_s: 0, updated_at: null })
    fireEvent.click(screen.getByRole('button', { name: 'Reset voice profile' }))
    expect(await screen.findByText(/No voice profile yet/)).toBeInTheDocument()
    expect(h.voice.reset).toHaveBeenCalled()
  })
```

- [ ] **Step 2: Run to verify failure**

Run: `cd frontend && npm test -- --run src/components/ToneMatrix.test.tsx src/pages/Stats.test.tsx src/pages/Settings.test.tsx`
Expected: FAIL.

- [ ] **Step 3: Implement**

Types and client as listed under Interfaces (`voiceProfile: { get: () => req<VoiceProfile>('/voice-profile'), reset: () => req<void>('/voice-profile', { method: 'DELETE' }) }` next to `stats` in `api`).

`frontend/src/components/ToneMatrix.tsx`:
```tsx
import type { ToneStats } from '../api/types'
import { pct } from '../lib/score'

const T = [0, 1, 2, 3, 4]
// Previous tone × tone (spec §6): sandhi contexts such as 3-3 stand out. Cells with fewer than 5 scores are dimmed.
export default function ToneMatrix({ pairs }: { pairs: ToneStats['pairs'] }) {
  const at = new Map(pairs.map((p) => [`${p.prev_tone}-${p.tone}`, p]))
  const cls = (m: number) => (m >= 0.7 ? 'cell-ok' : m >= 0.5 ? 'cell-warn' : 'cell-bad')
  return (
    <table className="text-xs text-center border-separate border-spacing-1">
      <thead><tr><th className="text-fgdim font-normal">prev ↓ · tone →</th>{T.map((t) => <th key={t} className="text-fgdim font-normal w-10">{t}</th>)}</tr></thead>
      <tbody>{T.map((p) => (
        <tr key={p}><th className="text-fgdim font-normal">{p}</th>
          {T.map((t) => {
            const c = at.get(`${p}-${t}`)
            if (!c) return <td key={t} className="cell-neutral border rounded h-8">·</td>
            return <td key={t} title={`after tone ${p}, tone ${t}: ${pct(c.mean)} (n ${c.n})`} className={`${cls(c.mean)} border rounded h-8 ${c.n < 5 ? 'opacity-40' : ''}`}>{pct(c.mean)}</td>
          })}
        </tr>))}
      </tbody>
    </table>
  )
}
```

`frontend/src/components/ToneTrend.tsx`: an SVG line chart in the style of `ActivityChart` in `Stats.tsx` (viewBox 720×160, recessive axis lines `#2a3139`, labels `#7c8793`), x = the distinct weeks in order, y = mean ×100 on a fixed 0–100 scale, one `<path>` per tone that has data, colours from the `dataviz` skill's categorical palette for five series, a legend `Tone 1 (high)` … `Neutral`, `role="img"` and `aria-label="Tone scores per week, last 12 weeks"`, and a `<details>` table fallback like `ActivityChart`. Weeks with no score for a tone leave a gap.

`frontend/src/pages/Stats.tsx`:
- `EMPTY = 'No scores yet — record a take to see tone stats.'`
- **Characters** panel: rows `<span className="font-hanzi text-fghi">{s.ch}</span> <span>{s.pinyin}{s.tone}</span> <span>mean {pct(s.mean)}</span> <span className="text-fgdim">n {s.n}</span>` and, when `trend != null`, `<span className={s.trend >= 0 ? 'text-ok' : 'text-bad'}>{s.trend >= 0 ? '↑' : '↓'} {Math.abs(Math.round(s.trend * 100))}</span>`
- **Tones** panel: `<ToneTrend weeks={tones.weeks} />`, then the per-tone rows as `Tone {t} ({TONE_NAMES[t]})`, then `<h3 className="text-sm text-fgdim">After tone × tone</h3><ToneMatrix pairs={tones.pairs} />`

`frontend/src/pages/Settings.tsx` — a **Voice profile** section (same section style as the others):
```tsx
  const [voice, setVoice] = useState<VoiceProfile | null>(null)
  useEffect(() => { api.voiceProfile.get().then(setVoice).catch(() => setVoice(null)) }, [])
  async function resetVoice() {
    if (!window.confirm('Reset your voice profile? Your next takes rebuild it.')) return
    await api.voiceProfile.reset(); setVoice(await api.voiceProfile.get())
  }
```
```tsx
      <section …>
        <h2 className="text-fghi">Voice profile</h2>
        <p className="text-sm text-fgdim">{voice?.baseline_hz != null
          ? `Your baseline: ${Math.round(voice.baseline_hz)} Hz · range ${voice.spread_st!.toFixed(1)} st · from ${(voice.voiced_s / 60).toFixed(1)} min of speech`
          : 'No voice profile yet: it builds from your first scored takes.'}</p>
        <p className="text-xs text-fgdim">Tone scores compare your pitch movement to your own baseline, so a lower or narrower voice is not penalised. Reset it when someone else practises or your voice has changed.</p>
        <button onClick={() => void resetVoice()}>Reset voice profile</button>
      </section>
```

- [ ] **Step 4: Run the frontend checks**

Run: `cd frontend && npm test -- --run && npx eslint . && npx tsc -b`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(frontend): tone trend, tone-pair matrix, weakest characters; voice profile in Settings"
```

---

### Task 15: Rescore the user's takes, sanity report, gate thresholds (needs Task 8's model)

**Files:**
- Create: `backend/shadow/scoring/report.py`, `backend/scripts/rescore.py`, `backend/tests/test_report.py`, `backend/tests/test_tone_model_real.py`
- Modify: `backend/shadow/config.py` and `config.toml` (`min_rms_dbfs`, `min_align_conf`), `backend/tests/test_config.py` (`test_phase2_scoring_defaults`), this plan's **Ledger**

**Interfaces:**
- Consumes: `score_attempt`, `reset_profile`, `trim_silence`, `build_deps`, `init_db`, `make_engine`.
- Produces: `@dataclass ReportItem(attempt_id: int, segment_id: int, lesson_title: str, text: str, created_at: str, score: dict | None)`; `render_report(items: list[ReportItem], api_base: str) -> str`; CLI `scripts/rescore.py [--probe] [--api http://127.0.0.1:8000]`.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_report.py`:
```python
from shadow.scoring.report import ReportItem, render_report


def test_report_lists_verdicts_audio_and_warnings():
    score = {"overall": 0.62, "warnings": [], "syllables": [
        {"ch": "你", "status": "ok", "target_tone": 2, "heard_tone": 2, "tone_score": 0.91},
        {"ch": "好", "status": "wrong", "target_tone": 3, "heard_tone": 2, "tone_score": 0.33}]}
    gated = {"overall": None, "warnings": ["too_quiet"], "syllables": []}
    html = render_report([ReportItem(7, 11, "L <1>", "你好", "2026-10-07 09:32", score),
                          ReportItem(8, 11, "L <1>", "你好", "2026-10-07 09:33", gated)], "http://127.0.0.1:8000")
    assert "L &lt;1&gt;" in html and "3→2" in html and "62" in html
    assert 'src="http://127.0.0.1:8000/segments/11/audio?fmt=wav"' in html
    assert 'src="http://127.0.0.1:8000/attempts/7/audio"' in html
    assert "too_quiet" in html
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_report.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

`backend/shadow/scoring/report.py`:
```python
"""The rescore sanity report (Phase 2 spec §5.4): per take, the verdicts next to the audio, for a listener to skim."""
from __future__ import annotations
from dataclasses import dataclass
from html import escape

_BG = {"ok": "#17442d", "close": "#4d3a12", "wrong": "#4a1d22", "unvoiced": "#1a1f26", "missing": "transparent"}


@dataclass
class ReportItem:
    attempt_id: int
    segment_id: int
    lesson_title: str
    text: str
    created_at: str
    score: dict | None


def _cell(s: dict) -> str:
    mark = (f"{s['target_tone']}→{s['heard_tone']}" if s["status"] == "wrong"
            else "∅" if s["status"] == "unvoiced" else "–" if s.get("tone_score") is None
            else str(round(s["tone_score"] * 100)))
    return (f'<span class="c" style="background:{_BG.get(s["status"], "#222")}" title="{escape(s["status"])}">'
            f'{escape(s["ch"])}<small>{escape(mark)}</small></span>')


def render_report(items: list[ReportItem], api_base: str) -> str:
    rows = []
    for it in items:
        sc = it.score or {}
        overall = sc.get("overall")
        head = str(round(overall * 100)) if overall is not None else escape(", ".join(sc.get("warnings") or ["not scored"]))
        rows.append(
            f"<tr><td>{it.attempt_id}<br><small>{escape(it.created_at)}</small></td>"
            f"<td>{escape(it.lesson_title)}<br>{escape(it.text)}</td><td>{head}</td>"
            f"<td>{''.join(_cell(s) for s in sc.get('syllables') or [])}</td>"
            f'<td><audio controls preload="none" src="{api_base}/segments/{it.segment_id}/audio?fmt=wav"></audio><br>'
            f'<audio controls preload="none" src="{api_base}/attempts/{it.attempt_id}/audio"></audio></td></tr>')
    return ("<!doctype html><meta charset=utf-8><title>Rescore report</title><style>"
            "body{background:#0f1215;color:#cfd6dd;font:14px system-ui}td{border-bottom:1px solid #2a3139;padding:6px;vertical-align:top}"
            ".c{display:inline-block;margin:1px;padding:2px 4px;border:1px solid #2a3139;border-radius:3px;text-align:center}"
            ".c small{display:block;font-size:10px}</style>"
            "<p>Reference (top) and your take (bottom) per row; the backend must be running for the audio.</p>"
            f"<table>{''.join(rows)}</table>")
```

`backend/scripts/rescore.py`:
```python
"""Re-score every stored take (Phase 2 spec §5.4) and write a sanity report.

    cd backend && ~/.local/bin/uv run python scripts/rescore.py [--probe]
Clears all SyllableScore rows and the voice profile, then scores takes oldest first (the profile rebuilds as it
goes). --probe also aligns each take to the *next* sentence's text and prints level and alignment-confidence
percentiles for genuine and wrong-text takes, to set the gate thresholds (plan Task 15)."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import date
from pathlib import Path
import numpy as np
from sqlmodel import Session, delete, select
from shadow.config import load_settings
from shadow.deps import build_deps
from shadow.ingest import audio
from shadow.scoring import score_attempt
from shadow.scoring.pitch import trim_silence
from shadow.scoring.profile import reset_profile
from shadow.scoring.report import ReportItem, render_report
from shadow.store.db import init_db, make_engine
from shadow.store.models import Attempt, Lesson, Segment, SyllableScore


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--api", default="http://127.0.0.1:8000")
    a = ap.parse_args()
    settings = load_settings()
    engine = make_engine(settings.data_dir); init_db(engine)
    deps = build_deps(settings)
    if deps.tone_model is None:
        raise SystemExit("no tone model: train it first (make tone-model)")
    items, warn, dbfs, conf, wrong_conf = [], Counter(), [], [], []
    with Session(engine) as db:
        db.exec(delete(SyllableScore)); reset_profile(db); db.commit()
        atts = db.exec(select(Attempt).where(Attempt.audio_path != "").order_by(Attempt.created_at, Attempt.id)).all()
        for att in atts:
            if not Path(att.audio_path).exists():
                continue
            seg = db.get(Segment, att.segment_id)
            score_attempt(deps, db, seg, att)
            db.add(att); db.commit()
            sj = att.score_json or {}
            warn.update(sj.get("warnings") or ["scored"])
            q = sj.get("quality") or {}
            if q.get("dbfs") is not None: dbfs.append(q["dbfs"])
            if q.get("align_conf") is not None: conf.append(q["align_conf"])
            if a.probe:
                other = db.exec(select(Segment).where(Segment.lesson_id == seg.lesson_id, Segment.idx == seg.idx + 1)).first()
                if other is not None:
                    wav, sr = audio.read_wav(Path(att.audio_path))
                    spans = deps.aligner.align(trim_silence(wav, sr)[0], sr, other.text)
                    if spans: wrong_conf.append(float(np.mean([s.conf for s in spans])))
            items.append(ReportItem(att.id, seg.id, db.get(Lesson, seg.lesson_id).title, seg.text, str(att.created_at)[:16], sj))
    out = settings.data_dir / "reports" / f"rescore-{date.today().isoformat()}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_report(items, a.api), encoding="utf-8")
    scored = [i.score["overall"] for i in items if i.score and i.score.get("overall") is not None]
    print(f"{len(items)} takes; outcomes {dict(warn)}; mean overall {np.mean(scored):.2f}" if scored else f"{len(items)} takes; {dict(warn)}")
    pc = lambda xs: np.round(np.percentile(xs, [0, 5, 50, 95, 100]), 3).tolist() if xs else []
    print(f"dbfs p0/5/50/95/100: {pc(dbfs)}\nalign_conf (genuine): {pc(conf)}")
    if a.probe:
        print(f"align_conf (next sentence's text): {pc(wrong_conf)}")
    print(f"report: {out}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test, commit the tool**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_report.py -q` (expected PASS)
```bash
git add backend/shadow/scoring/report.py backend/scripts/rescore.py backend/tests/test_report.py
git commit -m "feat(backend): rescore script and sanity report"
```

- [ ] **Step 5: Real-model check on synthetic tones (`-m models`)**

`backend/tests/test_tone_model_real.py`:
```python
import pytest
from shadow.config import ScoringCfg
from shadow.ingest.align import FakeAligner
from shadow.scoring.pitch import baseline_of, track_pitch
from shadow.scoring.score import RefData, score_take
from shadow.scoring.tone import load_tone_model
from tests.helpers import voice

pytestmark = pytest.mark.models
SR, TEXT = 16000, "妈麻马骂"                                   # mā má mǎ mà
SYLS = [{"ch": c, "pinyin": "ma", "pinyin_toneless": "ma", "tone": t} for c, t in zip(TEXT, [1, 2, 3, 4])]
SHAPES = [(240, 240), (170, 250), (150, 125), (260, 140)]


def _score(model, ref, shapes):
    return score_take(ref=ref, syllables=SYLS, text=TEXT, wav=voice(shapes, syl_s=0.3), sr=SR, aligner=FakeAligner(),
                      model=model, profile=None, profile_voiced_s=0.0, cfg=ScoringCfg()).json["syllables"]


def test_real_model_flags_a_flattened_fourth_tone_and_nothing_in_a_copy():
    model = load_tone_model("tone_v1")
    assert model is not None
    ref_wav = voice(SHAPES, syl_s=0.3)
    p = track_pitch(ref_wav, SR)
    ref = RefData(p, [(s.start, s.end) for s in FakeAligner().align(ref_wav, SR, TEXT)], baseline_of(p.voiced()))
    assert all(s["status"] != "wrong" for s in _score(model, ref, SHAPES))
    assert _score(model, ref, SHAPES[:3] + [(240, 240)])[3]["status"] != "ok"
```
Run: `cd backend && ~/.local/bin/uv run pytest -m models tests/test_tone_model_real.py -q`. Expected: PASS. Synthetic harmonic tones are not speech: if the copy gets a `wrong` cell, record the per-syllable verdicts in the Ledger and tell the user rather than tuning the model to synthetic input. Commit the test with Step 7.

- [ ] **Step 6: Probe the user's takes and set the gate thresholds**

Back up the database first (`cp data/shadow.db data/shadow.db.bak-phase2`), make sure no backend server is writing to it, then:
```bash
cd backend && ~/.local/bin/uv run python scripts/rescore.py --probe
```
Set the thresholds from the printed percentiles:
- `min_align_conf` = the midpoint between the genuine 5th percentile and the wrong-text 95th percentile, rounded to 0.01. If the two overlap (wrong-text p95 ≥ genuine p5), use the genuine 2nd-percentile value instead and write "overlap: wrong_or_unclear will miss some wrong-sentence takes" in the Ledger.
- `min_rms_dbfs` = the genuine minimum − 6 dB, rounded to an integer, but no higher than −40.

Write both values into `ScoringCfg` defaults, `config.toml` and `test_phase2_scoring_defaults`; record the printed lines and the chosen values in the Ledger. Run `cd backend && ~/.local/bin/uv run pytest -q`, then rescore once more without `--probe` and record its outcome line. If more than 20 % of the user's genuine takes end up gated, stop and report to the user before committing.

- [ ] **Step 7: Commit**

```bash
git add backend/shadow/config.py config.toml backend/tests/test_config.py backend/tests/test_tone_model_real.py docs/superpowers/plans/2026-10-09-phase2-tone-scoring.md
git commit -m "feat(backend): gate thresholds set from the user's takes (plan ledger)"
```
Tell the user the report path (`data/reports/rescore-<date>.html`; open it in Brave on Windows via `\\wsl$\…` with the backend running) and ask him to skim whether red lands where it sounds wrong.

---

### Task 16: Docs and acceptance checklist

**Files:**
- Create: `docs/phase2-acceptance.md`
- Modify: `README.MD` (Roadmap, Stats and feedback sections), `docs/running.md`

- [ ] **Step 1: Write the docs**

`docs/running.md` — a **Tone scoring** section:
- the tone model ships in `backend/shadow/scoring/models/`; nothing to download for normal use;
- retraining: `make tone-model LABELS=<canonical|realised>` (the value recorded in the plan ledger), ~19 GB download into `data/corpora/aishell3`, 1–2 h on the GPU, needs the models extra; AISHELL-3 is Apache-2.0;
- `make rescore` after a model or feature change, and where the report goes;
- the voice profile and its reset in Settings;
- gate warnings and what to do about each (the texts of `WARNINGS` in `frontend/src/lib/score.ts`).

`README.MD`:
- Roadmap: move Phase 2 to **Built** (one line: tone scoring per syllable from a classifier trained on AISHELL-3 plus contour similarity, both normalised to each speaker's own baseline; pitch lines; stats per tone, tone pair and character); Phase 3 becomes **Next**.
- Replace "Per-sentence, per-character and per-tone scores arrive with tone scoring" with a sentence describing the new Stats panels.
- In the feedback block description, describe the colours (green, orange, red with `3→2`, grey ∅, dashed missing) and the pitch lines.

`docs/phase2-acceptance.md` — a checklist the user runs in the browser:
```markdown
# Phase 2 acceptance — tone scoring

- [ ] `/health` shows `tone_model.loaded: true` and the version from the ledger.
- [ ] Echo a sentence you know well: most cells green, a score in the header, two pitch lines on the You track.
- [ ] Echo the same sentence with one tone deliberately wrong (e.g. say 好 rising): that cell turns red and shows `3→2` (or orange), the others stay green.
- [ ] Say a different sentence than the one shown: "Could not match this to the sentence — not scored."
- [ ] Whisper or record from across the room: "Too quiet — not scored."
- [ ] Reopen the lesson: the last take's colours and pitch lines come back.
- [ ] Flow a passage: rows take a colour as their slices are scored; the summary shows a mean and the weakest lines.
- [ ] Stats: tone means, the weekly chart, the tone-pair matrix (3-3 cells after a sandhi-heavy lesson) and the weakest characters.
- [ ] Settings → Voice profile shows your baseline; Reset empties it and the next takes rebuild it.
- [ ] Skim `data/reports/rescore-<date>.html`: red cells land where the take sounds wrong.
- [ ] `cd backend && ~/.local/bin/uv run pytest -m models -q` passes.
```

- [ ] **Step 2: Full check and commit**

Run: `make test`
Expected: backend tests, frontend tests, eslint and tsc all pass.
```bash
git add README.MD docs/running.md docs/phase2-acceptance.md
git commit -m "docs: Phase 2 tone scoring in the README, running notes and acceptance checklist"
```

---

## Revision 2026-10-11 — speech-model tone features (spec §10)

Task 8's pitch-only model reached 75.1 % (below the 85 % gate); the user chose speech-model features. Tasks 17–19 replace the classifier's features (order 17 → 20 → 18 → 19, spec §10.1 adds Task 20); Task 15 Steps 5–7 run after Task 19. Global Constraints change: `FEATURE_VERSION = 2`; `unvoiced` status only for non-hanzi characters (tone −1).

### Task 17: Speech-model embedder and v2 features in scoring

**Files:**
- Create: `backend/shadow/scoring/embed.py`, `backend/tests/test_embed.py`
- Modify: `backend/shadow/scoring/features.py`, `backend/shadow/scoring/score.py`, `backend/shadow/scoring/reference.py`, `backend/shadow/scoring/__init__.py`, `backend/shadow/config.py` (`ModelsCfg`), `config.toml` (`[models]`), `backend/shadow/deps.py`, `backend/pyproject.toml` (+ `uv.lock`), `backend/tests/test_features.py`, `backend/tests/test_score.py`, `backend/tests/test_tone.py` (only if it asserts `FEATURE_VERSION == 1`)

**Interfaces:**
- Produces:
  - `embed.py`: `FRAME_S = 0.02`, `DIM = 768`; `class Embedder(Protocol): def frames(self, wav: np.ndarray, sr: int) -> np.ndarray` (shape `(T, DIM)`, float32, one row per 20 ms frame); `FakeEmbedder()` (deterministic, no model); `Wav2Vec2Embedder(name: str, revision: str, layer: int, device: str)` with a lazily loaded `_model` and a lock; `pool(frames: np.ndarray, spans: list[tuple[float, float]]) -> np.ndarray` (shape `(len(spans), DIM)`).
  - `features.py`: `FEATURE_VERSION = 2`; `N_PITCH = 45` (the old `N_FEATURES` value, renamed); `N_FEATURES = 3 * DIM + 2 + N_PITCH` (= 2351); `pitch_matrix(sylls) -> np.ndarray` (the old `feature_matrix`, renamed, unchanged output); `feature_matrix(sylls: list[SylPitch], pooled: np.ndarray) -> np.ndarray` (rows `[own, prev, prev_flag, next, next_flag, pitch45]`, float32).
  - `RefData` gains `wav: np.ndarray` and `sr: int` (the reference clip samples); `score_take(..., embedder: Embedder, ...)` gains a keyword `embedder`.
  - `ModelsCfg.tone_embedder = "TencentGameMate/chinese-wav2vec2-base"`, `tone_embedder_revision = "3991242c806928916fff4a8c0e4f76acf661b743"`, `tone_layer = 6`.
  - `Deps.embedder: Embedder | None` (real: `Wav2Vec2Embedder(...)` on the resolved device; fake: `FakeEmbedder()`); `loaded_models()` lists `"embedder"` once its `_model` is loaded.

- [ ] **Step 1: Dependency**

`transformers` is installed only transitively. Make it explicit in the `models` extra: `cd backend && ~/.local/bin/uv add --no-sync --optional models "transformers>=4.57"` then `~/.local/bin/uv sync --extra dev --extra models`.

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_embed.py`:
```python
import numpy as np
import pytest
from shadow.scoring.embed import DIM, FRAME_S, FakeEmbedder, pool


def test_fake_embedder_shape_and_determinism():
    wav = np.linspace(-0.5, 0.5, 16000, dtype=np.float32)
    a, b = FakeEmbedder().frames(wav, 16000), FakeEmbedder().frames(wav, 16000)
    assert a.shape == (50, DIM) and a.dtype == np.float32 and np.array_equal(a, b)


def test_pool_means_frames_whose_centres_fall_in_the_span():
    frames = np.repeat(np.arange(10, dtype=np.float32)[:, None], DIM, axis=1)   # frame i holds value i
    out = pool(frames, [(0.0, 0.05), (0.06, 0.1), (0.5, 0.6)])
    # centres: 0.0125, 0.0325, 0.0525 … → span 1 takes frames 0,1; span 2 takes frames 3,4
    assert out.shape == (3, DIM)
    assert out[0, 0] == pytest.approx(0.5) and out[1, 0] == pytest.approx(3.5)
    assert out[2, 0] == 9.0                                                     # beyond the end: nearest frame


def test_pool_empty_span_takes_nearest_frame():
    frames = np.repeat(np.arange(10, dtype=np.float32)[:, None], DIM, axis=1)
    assert pool(frames, [(0.041, 0.042)])[0, 0] == 2.0
    assert FRAME_S == 0.02
```

Replace the bodies of `test_feature_matrix_shape_and_neighbours` and `test_feature_matrix_single_syllable_has_empty_neighbours` in `backend/tests/test_features.py` (and update the import line: `pitch_matrix`, `N_PITCH` instead of the old names where used):
```python
def test_pitch_matrix_shape_and_neighbours():
    up = SylPitch(np.linspace(-1, 1, POINTS), 1.0, 0.2)
    down = SylPitch(np.linspace(1, -1, POINTS), 1.0, 0.2)
    quiet = SylPitch(None, 0.1, 0.1)
    X = pitch_matrix([up, down, quiet])
    assert X.shape == (3, N_PITCH) and X.dtype == np.float32
    assert np.allclose(X[0, :POINTS], up.contour) and not np.allclose(X[0], X[1])


def test_feature_matrix_concatenates_embeddings_context_and_pitch():
    from shadow.scoring.embed import DIM
    sylls = [SylPitch(np.zeros(POINTS), 1.0, 0.2), SylPitch(None, 0.0, 0.1), SylPitch(np.ones(POINTS), 1.0, 0.2)]
    pooled = np.stack([np.full(DIM, i + 1, np.float32) for i in range(3)])
    X = feature_matrix(sylls, pooled)
    assert X.shape == (3, N_FEATURES) and N_FEATURES == 3 * DIM + 2 + N_PITCH and FEATURE_VERSION == 2
    own, prv, pflag = X[1, :DIM], X[1, DIM:2 * DIM], X[1, 2 * DIM]
    nxt, nflag = X[1, 2 * DIM + 1:3 * DIM + 1], X[1, 3 * DIM + 1]
    assert own[0] == 2 and prv[0] == 1 and pflag == 1 and nxt[0] == 3 and nflag == 1
    assert X[0, 2 * DIM] == 0 and np.all(X[0, DIM:2 * DIM] == 0)          # no previous syllable
    assert X[2, 3 * DIM + 1] == 0                                          # no next syllable
    assert np.allclose(X[:, -N_PITCH:], pitch_matrix(sylls))
```

In `backend/tests/test_score.py`:
- `ref_data` builds `RefData(p, spans, baseline_of(p.voiced()), wav, SR)`;
- every `score_take(...)` call (in `run` and in `test_tiny_take_is_gated_before_pitch`) passes `embedder=FakeEmbedder()` (import it from `shadow.scoring.embed`);
- add:
```python
def test_pitch_unvoiced_syllable_is_still_judged_without_contour():
    import shadow.scoring.score as score
    real = score.syllable_pitch
    def no_pitch_on_third(norm, t0, start, end, min_voiced):          # pretend syllable 3 has no voiced frames
        s = real(norm, t0, start, end, min_voiced)
        return score.SylPitch(None, 0.0, s.duration) if 0.5 <= start < 0.75 else s
    import pytest as _p
    mp = _p.MonkeyPatch(); mp.setattr(score, "syllable_pitch", no_pitch_on_third)
    try:
        syl = run(voice(REF_CONTOURS)).json["syllables"][2]
    finally:
        mp.undo()
    assert syl["status"] in ("ok", "close") and syl["contour"] is None and syl["tone_score"] == pytest.approx(syl["p_target"])
```
(`test_non_hanzi_syllable_is_unvoiced` stays as is: tone −1 is still `unvoiced`.)

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_embed.py tests/test_features.py tests/test_score.py -q`
Expected: FAIL (module `shadow.scoring.embed` missing, names missing).

- [ ] **Step 4: Implement**

`backend/shadow/scoring/embed.py`:
```python
"""Speech-model embeddings for the tone classifier (Phase 2 spec §10): one hidden layer of a pretrained Chinese
wav2vec2, mean-pooled over each aligned syllable. Raw 16 kHz input, fp32, exactly as the model was trained."""
from __future__ import annotations
import threading
from typing import Protocol
import numpy as np

FRAME_S = 0.02                           # wav2vec2 frame step at 16 kHz
DIM = 768
_CENTRE = 0.0125                         # frame i covers ~[i·20 ms, i·20 ms + 25 ms]


class Embedder(Protocol):
    def frames(self, wav: np.ndarray, sr: int) -> np.ndarray: ...


class FakeEmbedder:
    """Tests: every dimension of frame i holds the mean absolute amplitude of its 20 ms (no model)."""
    def frames(self, wav: np.ndarray, sr: int) -> np.ndarray:
        hop = int(FRAME_S * sr)
        n = max(len(wav) // hop, 1)
        e = np.abs(np.asarray(wav, np.float32)[: n * hop]).reshape(n, hop).mean(axis=1) if len(wav) >= hop else np.zeros(1)
        return np.repeat(e[:, None], DIM, axis=1).astype(np.float32)


class Wav2Vec2Embedder:
    def __init__(self, name: str, revision: str, layer: int, device: str):
        self.name, self.revision, self.layer, self.device = name, revision, layer, device
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        if self._model is None:
            from transformers import Wav2Vec2Model
            self._model = Wav2Vec2Model.from_pretrained(self.name, revision=self.revision).to(self.device).eval()
        return self._model

    def frames(self, wav: np.ndarray, sr: int) -> np.ndarray:
        import torch
        import torchaudio.functional as AF
        with self._lock:
            model = self._load()
            x = torch.from_numpy(np.asarray(wav, np.float32))[None].to(self.device)
            if sr != 16000:
                x = AF.resample(x, sr, 16000)
            with torch.inference_mode():
                hs = model(x, output_hidden_states=True).hidden_states[self.layer]
            return hs[0].float().cpu().numpy()


def pool(frames: np.ndarray, spans: list[tuple[float, float]]) -> np.ndarray:
    """Mean of the frames whose centre lies inside each [start, end]; the nearest frame when none does."""
    centres = np.arange(len(frames)) * FRAME_S + _CENTRE
    out = np.zeros((len(spans), frames.shape[1]), np.float32)
    for i, (a, b) in enumerate(spans):
        idx = np.flatnonzero((centres >= a) & (centres <= b))
        out[i] = frames[idx].mean(axis=0) if len(idx) else frames[int(np.argmin(np.abs(centres - (a + b) / 2)))]
    return out
```

`backend/shadow/scoring/features.py`:
- `FEATURE_VERSION = 2`; rename `N_FEATURES` → `N_PITCH` and `feature_matrix` → `pitch_matrix` (body unchanged, it returns `(n, N_PITCH)`);
- import `DIM` from `shadow.scoring.embed`; add:
```python
N_FEATURES = 3 * DIM + 2 + N_PITCH         # own, previous (+flag), next (+flag) embeddings, then the pitch features


def feature_matrix(sylls: list[SylPitch], pooled: np.ndarray) -> np.ndarray:
    """The classifier's rows (spec §10): each syllable's pooled embedding, its neighbours' with presence flags,
    and its pitch features. Missing neighbours are zeros with flag 0."""
    n = len(sylls)
    zero = np.zeros(DIM, np.float32)
    P = pitch_matrix(sylls)
    rows = [np.concatenate([pooled[i], pooled[i - 1] if i > 0 else zero, [1.0 if i > 0 else 0.0],
                            pooled[i + 1] if i < n - 1 else zero, [1.0 if i < n - 1 else 0.0], P[i]])
            for i in range(n)]
    return np.asarray(rows, dtype=np.float32).reshape(n, N_FEATURES)
```
Update every other user of the old names (`grep -rn "N_FEATURES\|feature_matrix" backend/shadow backend/scripts backend/tests`); `scripts/tone_model.py` is rewritten in Task 18 — for now make it import `pitch_matrix as feature_matrix, N_PITCH as N_FEATURES` so it still imports.

`backend/shadow/scoring/score.py`:
- `RefData` gains `wav: np.ndarray` and `sr: int` (after `baseline`);
- `score_take` gains keyword `embedder: Embedder` (import from `shadow.scoring.embed`, with `pool`);
- replace `P_r, P_u = model.proba(feature_matrix(syl_r)), model.proba(feature_matrix(syl_u))` with:
```python
    emb_r = pool(embedder.frames(ref.wav, ref.sr), ref.spans)
    emb_u = pool(embedder.frames(trimmed, sr), [(s.start, s.end) for s in spans])
    P_r, P_u = model.proba(feature_matrix(syl_r, emb_r)), model.proba(feature_matrix(syl_u, emb_u))
```
- in the per-syllable loop, replace the `unvoiced` branch and the judging branch with:
```python
        elif s["tone"] < 0:
            js = _syl_json(s, "unvoiced", **common)
            target = heard = None
        else:
            # a syllable without voiced pitch (either track) is still classified; it just has no contour term (§10)
            target = target_tone(P_r[i], s["tone"], cfg.ref_confidence)
            sim = (None if target == 0 or r.contour is None or u.contour is None
                   else contour_similarity(r.contour, u.contour, cfg.dtw_band, model.dtw_norm))
            v = judge(P_u[i], target, sim, cfg)
            ...  (unchanged)
```

`backend/shadow/scoring/reference.py` — add:
```python
def reference_audio(seg: Segment) -> tuple[np.ndarray, int]:
    return audio.read_wav(Path(seg.clip_wav_path))
```
`backend/shadow/scoring/__init__.py` — build `RefData(ref_pitch, reference_spans(segment), ref_base, *reference_audio(segment))` and pass `embedder=deps.embedder`; if `deps.embedder is None` the result is `failed_result(syllables, ["no_tone_model"])`.

`backend/shadow/config.py` `ModelsCfg` — add after `gop_model`:
```python
    tone_embedder: str = "TencentGameMate/chinese-wav2vec2-base"      # Phase 2 spec §10 (MIT)
    tone_embedder_revision: str = "3991242c806928916fff4a8c0e4f76acf661b743"
    tone_layer: int = 6
```
and the same three keys under `[models]` in `config.toml`.

`backend/shadow/deps.py` — `Deps` gains `embedder: Embedder | None = None`; `build_deps` passes `embedder=Wav2Vec2Embedder(settings.models.tone_embedder, settings.models.tone_embedder_revision, settings.models.tone_layer, device)`; `fake_deps` passes `embedder=FakeEmbedder()`; `loaded_models()` also checks `("embedder", self.embedder)` for a loaded `_model`.

- [ ] **Step 5: Run all backend tests**

Run: `cd backend && ~/.local/bin/uv run pytest -q`
Expected: all pass. `FakeToneModel` ignores feature values, so API tests keep working. The current `tone_v1` model files (feature version 1, uncommitted) are now rejected by `load_tone_model` — expected until Task 19.

- [ ] **Step 6: Real-model smoke check**

```bash
cd backend && ~/.local/bin/uv run python -c "
import numpy as np
from shadow.scoring.embed import Wav2Vec2Embedder
from shadow.config import load_settings
s = load_settings(); m = s.models
e = Wav2Vec2Embedder(m.tone_embedder, m.tone_embedder_revision, m.tone_layer, s.resolved_device())
f = e.frames(np.random.default_rng(0).normal(0, 0.1, 48000).astype('float32'), 16000)
print(f.shape, f.dtype)"
```
Expected: `(149, 768) float32` (downloads ~360 MB on first use).

- [ ] **Step 7: Commit**

```bash
git add backend/shadow backend/tests backend/pyproject.toml backend/uv.lock config.toml
git commit -m "feat(backend): tone features from chinese-wav2vec2 layer 6; pitch-unvoiced syllables still judged"
```

---

### Task 20: Syllable windows in scoring (spec §10.1)

Runs before Task 18 (the training tool reuses `windows`).

**Files:**
- Create: `backend/shadow/scoring/windows.py`, `backend/tests/test_windows.py`
- Modify: `backend/shadow/scoring/score.py`, `backend/tests/test_score.py` (only if an assertion depends on raw spans)

**Interfaces:**
- Produces: `MAX_EXT = 0.5`, `TAIL = 0.15`; `windows(spans: list[tuple[float, float]], dur: float) -> list[tuple[float, float]]`.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_windows.py`:
```python
import pytest
from shadow.scoring.windows import windows


def test_window_runs_to_the_next_start():
    assert windows([(0.0, 0.1), (0.25, 0.3)], dur=1.0) == [(0.0, 0.25), (0.25, pytest.approx(0.45))]


def test_pause_caps_the_window_at_span_end_plus_tail():
    w = windows([(0.0, 0.1), (0.9, 1.0)], dur=2.0)            # next start 0.9 is > 0.5 after 0.0
    assert w[0] == (0.0, pytest.approx(0.25))


def test_last_window_never_passes_the_audio_end_and_never_ends_before_its_span():
    assert windows([(0.0, 0.2)], dur=0.3) == [(0.0, pytest.approx(0.3))]
    assert windows([(0.0, 0.7), (0.8, 0.9)], dur=1.0)[0] == (0.0, pytest.approx(0.8))   # long span: next start
    assert windows([(0.0, 0.2), (0.1, 0.3)], dur=1.0)[0] == (0.0, 0.2)                  # overlap: own end
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_windows.py -q` — expected FAIL (module missing).

- [ ] **Step 3: Implement**

`backend/shadow/scoring/windows.py`:
```python
"""Syllable windows (Phase 2 spec §10.1): MMS (CTC) spans stop at the last letter's peak, about half-way through
the syllable; pitch, embeddings and the contour overlay use the window up to where the next syllable starts."""
from __future__ import annotations

MAX_EXT = 0.5            # a window runs to the next start only if that is at most this far after its own start
TAIL = 0.15              # otherwise (a pause, or the last syllable) it ends this far after its span


def windows(spans: list[tuple[float, float]], dur: float) -> list[tuple[float, float]]:
    out = []
    for i, (a, b) in enumerate(spans):
        nxt = spans[i + 1][0] if i + 1 < len(spans) else None
        if nxt is not None and nxt <= max(b, a + MAX_EXT):
            e = nxt
        else:
            e = min(b + TAIL, nxt if nxt is not None else dur, dur)
        out.append((a, max(e, b)))
    return out
```
(This is the spike's `extend` rule from `.superpowers/sdd/2026-10-09-phase2-tone-scoring/spike-reference/common.py`, with the last syllable capped at the audio's end.)

In `backend/shadow/scoring/score.py::score_take`, after the span-count check:
```python
    ref_win = windows(ref.spans, len(ref.wav) / ref.sr)
    usr_win = windows([(s.start, s.end) for s in spans], len(trimmed) / sr)
```
and use `ref_win` / `usr_win` (instead of `ref.spans` / the raw learner spans) for `syllable_pitch`, `pool`, `rate_ratio` stays on raw spans, `_contour_json` spans (`usr_win` shifted by `off`), while the `missing` check (`u.duration < MIN_SPAN_S`) keeps using the raw learner span: compute `raw_dur = spans[i].end - spans[i].start` for it. `usr_dur`/`ref_dur` in the JSON report window durations.

- [ ] **Step 4: Run all backend tests, commit**

Run: `cd backend && ~/.local/bin/uv run pytest -q` (all pass; fix any score test whose numbers depended on raw spans by reasoning about windows, not by loosening bounds).
```bash
git add backend/shadow/scoring/windows.py backend/shadow/scoring/score.py backend/tests
git commit -m "feat(backend): score syllables over windows that reach the next syllable (MMS spans stop half-way)"
```

---

### Task 18: Training tool v2 (speech-model features, pitch-altered copies)

**Files:**
- Create: `backend/shadow/scoring/augment.py`, `backend/tests/test_augment.py`
- Modify: `backend/scripts/tone_model.py`

**Reference:** the spike's working extractor `.superpowers/sdd/2026-10-09-phase2-tone-scoring/spike-reference/aug_extract.py` (and `common.py`, `RESULTS.md`) — port its logic; production must use the app's own modules (`windows`, `Wav2Vec2Embedder`, `pool`, `feature_matrix`, `syllable_pitch`, `pitch_matrix`), not the spike's copies.

**Interfaces:**
- Consumes: Task 17 (`Wav2Vec2Embedder`, `pool`, `feature_matrix(sylls, pooled)`, `N_FEATURES`, `FEATURE_VERSION = 2`), Task 20 (`windows`).
- Produces:
  - `augment.py`: `LEVEL = 0.6`; `TEMPLATES = {1: [5,5,5,5,5], 2: [3,2.7,3,4,5], 3: [2,1.3,1,1,None], 4: [5,4.5,3.5,2,1]}`; `FRACS = [0.05, 0.27, 0.5, 0.73, 0.95]`; `contour_units(choice: int | str, rng: np.random.Generator) -> np.ndarray` (5 values in spread units; `"flat"` → zeros; `None` in a template → `rng.uniform(1, 3)`; `(levels − 3) · LEVEL · rng.uniform(0.7, 1.3) + rng.uniform(−0.3, 0.3)`); `resynth(wav, sr, wins, units, base: Baseline, floor, ceiling) -> np.ndarray` (parselmouth Manipulation → new PitchTier with a point at each FRACS position of each window at `base.hz · 2^(u · base.spread_st / 12)` → overlap-add resynthesis; `units=None` returns the input unchanged); `alter_choices(tones: list[int | None], rng) -> tuple[list, list[int]]` (per syllable a choice from {1,2,3,4,"flat"} minus its own tone; labels = imposed tone with flat → 1, or −1 when the own tone is 0/None).
  - `tone_model.py`: `--hours` default 10; per-speaker npz `X, y, ctx, contours, voiced, kind` where `kind` is 0 native, 1 altered, 2 flat (flat and the single altered copy only for test speakers); cache dir `features_v2_<labels>`; classifier `make_pipeline(StandardScaler(), MLPClassifier(hidden_layer_sizes=(256,), early_stopping=True, random_state=0))` trained on native + altered rows of training speakers; metadata adds `accuracy_altered`, `false_wrong_native`, `flat_still_original`, `embedder`, `layer`, `augmentation`; prints `ACCEPT` only if native ≥ 0.85 and altered ≥ 0.85.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_augment.py`:
```python
import numpy as np
import pytest
from shadow.scoring.augment import alter_choices, contour_units, resynth
from shadow.scoring.pitch import Baseline, track_pitch
from tests.helpers import voice

SR = 16000


def test_contour_units_shapes():
    rng = np.random.default_rng(0)
    assert np.all(contour_units("flat", rng) == 0)
    rise = contour_units(2, rng); fall = contour_units(4, rng)
    assert rise[-1] > rise[0] and fall[-1] < fall[0]
    assert np.ptp(contour_units(1, rng)) == pytest.approx(0.0)


def test_alter_choices_never_keeps_the_own_tone():
    rng = np.random.default_rng(1)
    for _ in range(50):
        ch, lab = alter_choices([1, 2, 3, 4, 0, None], rng)
        assert all(c != t for c, t in zip(ch[:4], [1, 2, 3, 4]))
        assert lab[4] == -1 and lab[5] == -1
        assert all(l == (1 if c == "flat" else c) for c, l in zip(ch[:4], lab[:4]))


def test_resynth_imposes_a_rise_on_a_flat_voice():
    wav = voice([(180, 180)], syl_s=0.6)
    base = Baseline(180.0, 4.0)
    out = resynth(wav, SR, [(0.0, 0.6)], [np.array([-1.0, -0.5, 0.0, 0.5, 1.0])], base, 60, 500)
    f0 = track_pitch(out, SR).voiced()
    assert len(out) == pytest.approx(len(wav), abs=SR // 100)
    assert f0[-5:].mean() > f0[:5].mean() * 1.2
    assert np.array_equal(resynth(wav, SR, [(0.0, 0.6)], None, base, 60, 500), wav)
```

- [ ] **Step 2: Run to verify failure, then implement `augment.py`** (port `contour_units`, `resynth` and the choice/label logic from the spike's `aug_extract.py` lines 25–60 and 92–100, using `parselmouth.praat.call`), and run `tests/test_augment.py` until it passes.

- [ ] **Step 3: Rewrite the feature and train stages of `scripts/tone_model.py`**

Per speaker (one pass, GPU): for each picked utterance align (`MmsAligner`), keep `(u, wav, sr, spans)`; `p0 = track_pitch(wav, …)`; speaker baseline from all native `p0`; `wins = windows([(s.start, s.end) …], len(wav)/sr)`. Then for each version — native; for training speakers two altered copies; for test speakers one altered copy and one flat copy — build the audio (`resynth` with `alter_choices`/`contour_units`, or flat units), re-track its pitch, normalise with the **native** speaker baseline, compute `syllable_pitch` over `wins`, `pooled = pool(embedder.frames(audio, sr), wins)`, `F = feature_matrix(sylls, pooled)`, and keep rows whose label is usable (native: labelled tone; altered/flat: label ≠ −1) with `kind`, `ctx` (from native labels), `contours`, `voiced`. Train on `kind ∈ {0, 1}` rows of training speakers. Evaluate on test speakers: native accuracy (kind 0, overall + per tone), altered accuracy (kind 1, per imposed tone), false-"wrong" on native (`max P − P(true) ≥ 0.25`), flat still-original (kind 2 rows whose native tone is 2/3/4 and whose prediction equals that native tone — store the native tone alongside). `dtw_norm` from native voiced test rows as before. Memory: keep `X` as float32; 10 h ≈ 3 × 90k rows × 2351 × 4 B ≈ 2.5 GB.

- [ ] **Step 4: Smoke-test the train stage on fake features** (20 fake speakers with `kind` arrays; it must print the metrics and `(1, 5)` from `load_tone_model('smoke', …).proba(np.zeros((1, N_FEATURES)))`), then remove the scratch dir.

- [ ] **Step 5: Run all backend tests and commit**

```bash
git add backend/shadow/scoring/augment.py backend/tests/test_augment.py backend/scripts/tone_model.py
git commit -m "feat(backend): train the tone model on speech-model features with pitch-altered copies"
```

---

### Task 19: Train tone model v2 (operator task, long-running)

Controller-run, like Task 8.

- [ ] **Step 1:** `rm -f backend/shadow/scoring/models/tone_v1.*` (the uncommitted v1 files), then in the background with thread caps (`OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 OPENBLAS_NUM_THREADS=4`): `cd backend && ~/.local/bin/uv run python scripts/tone_model.py --labels realised > ../data/corpora/tone_model_v2.log 2>&1`.
- [ ] **Step 2:** If not `ACCEPT` (native and altered both ≥ 0.85): stop and report to the user. If `ACCEPT`: record metrics in the Ledger, check the joblib size (< 50 MB; if larger, report), and commit:
```bash
git add backend/shadow/scoring/models/tone_v1.joblib backend/shadow/scoring/models/tone_v1.json docs/superpowers/plans/2026-10-09-phase2-tone-scoring.md
git commit -m "feat(backend): tone model v1 on chinese-wav2vec2 features (metrics in the plan ledger)"
```
- [ ] **Step 3:** Continue with Task 15 Steps 5–7. Task 15's real-model test (`test_tone_model_real.py`) passes `embedder=` a `Wav2Vec2Embedder` built from `load_settings().models` and `RefData(..., ref_wav, SR)`. Task 16's docs: replace the training time and size lines with the v2 numbers (15 h, ~1 h, model download ~360 MB on first use) in Task 15's final commit.


---

## Ledger

Record here, with dates: Task 8 label check (counts and choice), the training metrics (accuracy, per tone, `dtw_norm`, train/test sizes, model file size); Task 15 probe percentiles, chosen `min_align_conf` / `min_rms_dbfs`, and the final rescore outcome line; any deviation from this plan and why.

### Ledger entries

- 2026-10-11 Task 8 (pitch-only, feature v1): AISHELL-3 labels are realised ('一 yi2 个 ge4' 1338 vs 'yi1' 66; '不 bu2 是 shi4' 585; '你 ni2 好 hao3' 21). 30 h, 218 speakers: held-out accuracy 0.751 (0: 0.51, 1: 0.75, 2: 0.77, 3: 0.68, 4: 0.82), false 'wrong' on native 16.1 % → BELOW 0.85; the user chose speech-model features (spec §10).
- 2026-10-11 spikes: chinese-wav2vec2-base layer 6 best; trained on native only it leaned on character identity (altered 47 %); with pitch-altered copies native 94.0 % / altered 95.1 % (spec §10.1). MMS spans cover ~half a syllable → windows (Task 20).
- 2026-10-11 Task 19 (feature v2): 10 h, 10349 utterances, 218 speakers, labels realised; rows native 114257 / altered 198863 / flat 15561; first train stage OOM-killed → 120k-row cap (R12). Result: native 0.944 (0: 0.92, 1: 0.954, 2: 0.925, 3: 0.939, 4: 0.960), altered 0.953 (1: 0.956, 2: 0.919, 3: 0.976, 4: 0.951), false 'wrong' on native 5.3 %, flat still-original 9.4 %, dtw_norm 4.374, train rows 120000 of 280948, n_test 16611, joblib 6.8 MB → ACCEPT.

