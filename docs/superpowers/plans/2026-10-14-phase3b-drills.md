# Phase 3b — Drills Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Drill page that picks the user's weakest tone, tone pair or character from his Phase 2 scores, queues ~10 sentences from all lessons containing it, runs listen-along → scored Echo take → retry-until-green (max 3), and shows first-vs-best progress per session and across sessions.

**Architecture:** Backend package `shadow/drill/` with pure-ish functions for focus ranking (`focus.py`), queue building (`queue.py`) and summaries (`summary.py`) over the existing `SyllableScore`/`Attempt`/`Segment` tables plus a new `DrillSession` table; one router `api/drill.py`. Frontend: a pure step machine `lib/drill.ts`, a `pages/Drill.tsx` page reusing the Practice components (TwoTrack, KaraokeSentence, CueLine, VolumeSliders, ClipPlayer, useMic), "Drill this" entry points on Stats, and `?idx=` support on Practice.

**Tech Stack:** FastAPI, SQLModel/SQLite, pytest; React 18, Vite 5, vitest 3, Tailwind (all existing).

**Spec:** `docs/superpowers/specs/2026-10-14-phase3b-drills-design.md` (read it first; Phase 2 spec for SyllableScore semantics).

## Global Constraints

- Focus kinds: `tone` (key `"1"`–`"4"`), `pair` (key `"p-t"`, p and t in 1–4), `char` (key = one hanzi). Neutral 0 and non-hanzi (-1) are never focuses. `sound` is reserved for Phase 3a — do not implement it.
- Weakness = mean tone_score over matching `SyllableScore` rows of attempts in the last `window_days`; `unvoiced` rows excluded; `missing` rows count 0; target tone = `coalesce(target_tone, tone)`; pair = (`prev_tone`, target tone).
- Config `[drill]`: `window_days = 30`, `min_rows = 8`, `queue_size = 10`, `max_tries = 3`, `max_per_lesson = 4`, `min_syllables = 4`, `max_syllables = 15`, `rotate_within = 0.05`.
- Drill takes are ordinary attempts: `POST /segments/{id}/attempts` with `mode=drill` and form field `drill_session_id`; Phase 2 scoring applies unchanged.
- A scored try = an attempt whose `score_json.overall` is not null; gate-warning takes never count as tries.
- "Green" = every target syllable's `SyllableScore.status == "ok"`.
- Do not modify `Practice.tsx` beyond the `?idx=` support in Task 8.
- Backend commands: `cd backend && ~/.local/bin/uv run pytest -q` (never `uv sync` without `--extra dev --extra models`). Frontend: `cd frontend && npm test -- --run && npx eslint . && npx tsc -b` (one pre-existing Drawer.tsx eslint warning).
- Match the surrounding code: dense why-comments, `from __future__ import annotations`, no new abstractions beyond those named here.
- Commits end with a blank line and the Co-Authored-By line of the session that writes them.

## Review Focus

- **A focus with too little data** (a brand-new user, a character seen in one sentence): `GET /drill/focuses` returns an empty list or omits it, and the page shows the "practise first" state — never a crash or a drill on noise. Tests: Task 2 (`test_focus_needs_min_rows_and_two_sentences_for_chars`), Task 7 (empty state).
- **Queue with deleted or rebuilding lessons**: segments of lessons not `ready` are never queued; a summary of a session whose segments were deleted skips them. Tests: Task 3 (`test_queue_skips_lessons_that_are_not_ready`), Task 4 (`test_summary_skips_deleted_segments`).
- **Gate-warning takes in the retry loop**: they do not count as tries and do not end an item. Tests: Task 5 (`gate warning does not count`), Task 4 (`tries` counts scored takes only).
- **"Drill again" with segment_ids that no longer exist**: those are dropped; if none remain → 404. Test: Task 3 (`test_session_from_segment_ids`).
- **Leaving the page mid-drill**: the session is ended (best effort) and the start screen offers its summary. Test: Task 7 (unmount ends the session).

## File Structure

Backend (new): `backend/shadow/drill/__init__.py`, `focus.py`, `queue.py`, `summary.py`; `backend/shadow/api/drill.py`; tests `backend/tests/test_drill_focus.py`, `test_drill_queue.py`, `test_drill_api.py`.
Backend (modified): `config.toml`, `shadow/config.py`, `shadow/store/models.py`, `shadow/api/sessions.py` (`MODES`), `shadow/api/attempts.py`, `shadow/main.py`.
Frontend (new): `src/lib/drill.ts` (+ test), `src/pages/Drill.tsx` (+ test), `src/components/DrillSummary.tsx` (+ test).
Frontend (modified): `src/api/types.ts`, `src/api/client.ts`, `src/App.tsx`, `src/components/Shell.tsx`, `src/pages/Stats.tsx` (+ test), `src/components/ToneMatrix.tsx`, `src/pages/Practice.tsx` (`?idx=` only).
Docs: `README.MD`, `docs/phase3b-acceptance.md` (new).

---

### Task 1: Config, DrillSession table, drill attempts

**Files:** Modify `backend/shadow/config.py`, `config.toml`, `backend/shadow/store/models.py`, `backend/shadow/api/sessions.py`, `backend/shadow/api/attempts.py`; Test `backend/tests/test_drill_api.py` (new), `backend/tests/test_config.py`.

**Interfaces — Produces:** `DrillCfg` on `Settings.drill` with the Global Constraints values; `DrillSession(id, kind: str, key: str, label: str, started_at: datetime, ended_at: datetime | None, items_json: list[dict])`; `Attempt.drill_session_id: int | None` (FK `drillsession.id`); `"drill"` in `MODES`; `create_attempt` accepts form field `drill_session_id` (404 if given and unknown).

- [ ] **Step 1: Failing tests**

`backend/tests/test_config.py` append:
```python
def test_drill_defaults_and_config_toml():
    from pathlib import Path
    from shadow.config import Settings, load_settings
    d = Settings().drill
    assert (d.window_days, d.min_rows, d.queue_size, d.max_tries, d.max_per_lesson) == (30, 8, 10, 3, 4)
    assert (d.min_syllables, d.max_syllables, d.rotate_within) == (4, 15, 0.05)
    assert load_settings(Path(__file__).resolve().parents[2] / "config.toml").drill == d
```
`backend/tests/test_drill_api.py` (new):
```python
from sqlmodel import Session
from shadow.store.models import Attempt, DrillSession
from tests.helpers import make_tone_wav
from tests.test_lessons_api import _upload


def _post(client, path, sid, **data):
    with open(path, "rb") as f:
        return client.post(f"/segments/{sid}/attempts", files={"audio": ("a.wav", f, "audio/wav")}, data=data)


def test_a_drill_take_is_an_attempt_linked_to_its_drill_session(client, tmp_path):
    lid = _upload(client, tmp_path)
    sid = client.get(f"/lessons/{lid}").json()["segments"][0]["id"]
    with Session(client.app.state.engine) as db:
        ds = DrillSession(kind="tone", key="3", label="tone 3 (low)", items_json=[]); db.add(ds); db.commit(); db.refresh(ds)
    r = _post(client, make_tone_wav(tmp_path / "t.wav", 2.6), sid, mode="drill", drill_session_id=str(ds.id))
    assert r.status_code == 201
    with Session(client.app.state.engine) as db:
        assert db.get(Attempt, r.json()["id"]).drill_session_id == ds.id
    assert _post(client, make_tone_wav(tmp_path / "u.wav", 2.6), sid, mode="drill", drill_session_id="9999").status_code == 404
```

- [ ] **Step 2: Run → FAIL** (`cd backend && ~/.local/bin/uv run pytest tests/test_config.py tests/test_drill_api.py -q`).

- [ ] **Step 3: Implement**
- `config.py`: `class DrillCfg(BaseModel)` with the eight fields and defaults; `drill: DrillCfg = Field(default_factory=DrillCfg)` on `Settings`.
- `config.toml`: a `[drill]` block with the same eight keys and values.
- `models.py`: `class DrillSession(SQLModel, table=True)` with `__table_args__ = {"sqlite_autoincrement": True}`, fields as in Interfaces (`items_json` as `Field(default_factory=list, sa_column=Column(JSON))`, `started_at` default `now`), docstring "A drill (Phase 3b spec §3): the focus and the queue as built; its takes are attempts with drill_session_id."; `Attempt.drill_session_id: int | None = Field(default=None, foreign_key="drillsession.id")` (the existing in-place migration adds the nullable column).
- `sessions.py`: `MODES = {"echo", "chorus", "flow", "guided", "drill"}`.
- `attempts.py::create_attempt`: add `drill_session_id: int | None = Form(None)`; after the session check: `if drill_session_id is not None and db.get(DrillSession, drill_session_id) is None: raise HTTPException(404, "drill session not found")`; set `att.drill_session_id = drill_session_id` when creating the `Attempt`.
- Lesson delete (`_delete_lesson` in api/lessons.py) already deletes attempts — nothing to change; drill sessions stay.

- [ ] **Step 4: Run all backend tests → PASS; commit** `feat(backend): drill config, DrillSession table and drill attempts`

---

### Task 2: Focus ranking — `GET /drill/focuses`

**Files:** Create `backend/shadow/drill/__init__.py` (empty docstring module), `backend/shadow/drill/focus.py`, `backend/shadow/api/drill.py`; Modify `backend/shadow/main.py` (register router); Test `backend/tests/test_drill_focus.py`.

**Interfaces — Produces:**
- `@dataclass Focus(kind: str, key: str, label: str, mean: float, n: int)`
- `TONE_NAMES = {1: "high", 2: "rising", 3: "low", 4: "falling"}`
- `focus_label(kind: str, key: str, pinyin: str | None = None) -> str` — `"tone 3 (low)"`, `"tone pair 3→3"`, `"在 zai"` (pinyin_toneless when known, else the character alone)
- `rank_focuses(db: Session, cfg: DrillCfg, now: datetime | None = None) -> list[Focus]` — qualifying focuses, weakest first (ties: larger n first, then kind order tone < pair < char, then key)
- `auto_focus(db: Session, focuses: list[Focus], cfg: DrillCfg) -> Focus | None` — rotation rule
- Route `GET /drill/focuses` → `{"focuses": [Focus as dict], "auto": {"kind", "key"} | null}`

- [ ] **Step 1: Failing tests** — `backend/tests/test_drill_focus.py`:
```python
from datetime import datetime, timedelta, timezone
import pytest
from sqlmodel import Session
from shadow.config import DrillCfg
from shadow.drill.focus import auto_focus, focus_label, rank_focuses
from shadow.store.models import Attempt, DrillSession, Lesson, Segment, SyllableScore

NOW = datetime(2026, 10, 14, tzinfo=timezone.utc)


def _rows(db, rows, *, days_ago=1, seg_text="好"):
    """rows: (ch, pinyin, target_tone, prev_tone, score, status), each on its own attempt of one new segment."""
    les = Lesson(title="L", source_type="upload", status="ready"); db.add(les); db.commit()
    seg = Segment(lesson_id=les.id, idx=0, start_s=0, end_s=1, text=seg_text); db.add(seg); db.commit()
    for ch, py, t, p, score, status in rows:
        a = Attempt(segment_id=seg.id, mode="echo", audio_path="x.wav", duration_s=1.0, created_at=NOW - timedelta(days=days_ago))
        db.add(a); db.commit()
        db.add(SyllableScore(attempt_id=a.id, segment_id=seg.id, idx=0, ch=ch, pinyin_toneless=py, tone=t,
                             target_tone=t, prev_tone=p, tone_score=score, status=status))
    db.commit()


@pytest.fixture
def db(client):
    with Session(client.app.state.engine) as s:
        yield s


def test_labels():
    assert focus_label("tone", "3") == "tone 3 (low)"
    assert focus_label("pair", "3-3") == "tone pair 3→3"
    assert focus_label("char", "在", "zai") == "在 zai" and focus_label("char", "在") == "在"


def test_tone_and_pair_means_missing_counts_zero_unvoiced_ignored(db):
    _rows(db, [("好", "hao", 3, 3, 0.4, "close")] * 6 + [("好", "hao", 3, 3, None, "missing")] * 2
              + [("好", "hao", 3, 3, None, "unvoiced")] * 5)
    f = {(x.kind, x.key): x for x in rank_focuses(db, DrillCfg(), now=NOW)}
    assert f[("tone", "3")].n == 8 and f[("tone", "3")].mean == pytest.approx(0.3)
    assert f[("pair", "3-3")].n == 8


def test_focus_needs_min_rows_and_two_sentences_for_chars(db):
    _rows(db, [("在", "zai", 4, 1, 0.2, "wrong")] * 7)                    # 7 rows: below min_rows
    assert rank_focuses(db, DrillCfg(), now=NOW) == []
    _rows(db, [("在", "zai", 4, 1, 0.2, "wrong")] * 3)                    # 10 rows but one sentence each call…
    keys = {(x.kind, x.key) for x in rank_focuses(db, DrillCfg(), now=NOW)}
    assert ("tone", "4") in keys and ("char", "在") in keys               # …two sentences now (two _rows calls)


def test_window_and_neutral_excluded(db):
    _rows(db, [("的", "de", 0, 1, 0.1, "close")] * 10)                    # neutral: never a focus
    _rows(db, [("是", "shi", 4, 1, 0.1, "close")] * 10, days_ago=40)     # outside the 30-day window
    assert rank_focuses(db, DrillCfg(), now=NOW) == []


def test_weakest_first_and_rotation(db):
    _rows(db, [("好", "hao", 3, 1, 0.30, "close")] * 8)
    _rows(db, [("是", "shi", 4, 2, 0.33, "close")] * 8)
    fs = [f for f in rank_focuses(db, DrillCfg(), now=NOW) if f.kind == "tone"]
    assert [f.key for f in fs] == ["3", "4"]
    assert auto_focus(db, fs, DrillCfg()).key == "3"
    db.add(DrillSession(kind="tone", key="3", label="tone 3 (low)", items_json=[], ended_at=NOW)); db.commit()
    assert auto_focus(db, fs, DrillCfg()).key == "4"                      # last drill was tone 3, tone 4 within 0.05
    assert auto_focus(db, [], DrillCfg()) is None


def test_focuses_endpoint(client, db):
    _rows(db, [("好", "hao", 3, 3, 0.3, "close")] * 8)
    out = client.get("/drill/focuses").json()
    assert out["auto"] is not None and out["focuses"][0]["label"]
```
(Character tests: each `_rows` call creates a new segment, so two calls give two sentences.)

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement `backend/shadow/drill/focus.py`**
```python
"""Drill focuses (Phase 3b spec §1): which tone, tone pair or character is weakest in the recent scores."""
from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from sqlmodel import Session, select
from shadow.config import DrillCfg
from shadow.ingest.text import is_hanzi
from shadow.store.models import Attempt, DrillSession, SyllableScore

TONE_NAMES = {1: "high", 2: "rising", 3: "low", 4: "falling"}
_KIND_ORDER = {"tone": 0, "pair": 1, "char": 2}


@dataclass
class Focus:
    kind: str
    key: str
    label: str
    mean: float
    n: int


def focus_label(kind: str, key: str, pinyin: str | None = None) -> str:
    if kind == "tone":
        return f"tone {key} ({TONE_NAMES[int(key)]})"
    if kind == "pair":
        p, t = key.split("-")
        return f"tone pair {p}→{t}"
    return f"{key} {pinyin}" if pinyin else key


def rank_focuses(db: Session, cfg: DrillCfg, now: datetime | None = None) -> list[Focus]:
    """Qualifying focuses, weakest first. Missing syllables count 0 (as the sentence score does); unvoiced ones say
    nothing about tone and are left out."""
    since = (now or datetime.now(timezone.utc)) - timedelta(days=cfg.window_days)
    q = (select(SyllableScore.ch, SyllableScore.pinyin_toneless, SyllableScore.tone, SyllableScore.target_tone,
                SyllableScore.prev_tone, SyllableScore.tone_score, SyllableScore.status, SyllableScore.segment_id)
         .join(Attempt, Attempt.id == SyllableScore.attempt_id)
         .where(Attempt.created_at >= since, SyllableScore.status != "unvoiced"))
    scores: dict[tuple[str, str], list[float]] = defaultdict(list)
    sentences: dict[str, set[int]] = defaultdict(set)
    pinyin: dict[str, str] = {}
    for ch, py, tone, target, prev, score, status, seg_id in db.exec(q).all():
        v = 0.0 if status == "missing" else score
        if v is None:
            continue
        t = target if target is not None else tone
        if t in TONE_NAMES:
            scores[("tone", str(t))].append(v)
            if prev in TONE_NAMES:
                scores[("pair", f"{prev}-{t}")].append(v)
        if is_hanzi(ch):
            scores[("char", ch)].append(v)
            sentences[ch].add(seg_id)
            pinyin.setdefault(ch, py)
    out = []
    for (kind, key), vals in scores.items():
        if len(vals) < cfg.min_rows or (kind == "char" and len(sentences[key]) < 2):
            continue
        out.append(Focus(kind, key, focus_label(kind, key, pinyin.get(key)), sum(vals) / len(vals), len(vals)))
    return sorted(out, key=lambda f: (f.mean, -f.n, _KIND_ORDER[f.kind], f.key))


def auto_focus(db: Session, focuses: list[Focus], cfg: DrillCfg) -> Focus | None:
    """The weakest focus — unless the last finished drill had it and the next one is about as weak (rotation)."""
    if not focuses:
        return None
    last = db.exec(select(DrillSession).where(DrillSession.ended_at.is_not(None))
                   .order_by(DrillSession.ended_at.desc(), DrillSession.id.desc())).first()
    first = focuses[0]
    if (last is not None and (last.kind, last.key) == (first.kind, first.key) and len(focuses) > 1
            and focuses[1].mean - first.mean <= cfg.rotate_within):
        return focuses[1]
    return first
```
(If `is_hanzi` lives elsewhere, import it from where `shadow.scoring.gate` imports it.)

`backend/shadow/api/drill.py`:
```python
"""Drills (Phase 3b spec): focuses, sessions with their queue, summaries."""
from __future__ import annotations
from dataclasses import asdict
from fastapi import APIRouter, Depends, Request
from sqlmodel import Session
from shadow.drill.focus import auto_focus, rank_focuses
from shadow.store.db import get_session

router = APIRouter()


@router.get("/drill/focuses")
def focuses(request: Request, db: Session = Depends(get_session)):
    cfg = request.app.state.settings.drill
    fs = rank_focuses(db, cfg)
    auto = auto_focus(db, fs, cfg)
    return {"focuses": [asdict(f) for f in fs], "auto": {"kind": auto.kind, "key": auto.key} if auto else None}
```
Register `drill.router` in `main.py` with the others.

- [ ] **Step 4: All backend tests → PASS; commit** `feat(backend): drill focuses ranked by recent tone scores`

---

### Task 3: Queue and sessions — `POST/PATCH /drill/sessions`

**Files:** Create `backend/shadow/drill/queue.py`; Modify `backend/shadow/api/drill.py`; Test `backend/tests/test_drill_queue.py`.

**Interfaces — Consumes:** `Focus`, `focus_label` (Task 2); `_segment_out`, `_attempt_stats` (existing `shadow.api.lessons`); `segment_syllables` (`shadow.scoring.reference`).
**Produces:**
- `targets_for(syllables: list[dict], kind: str, key: str) -> list[int]` (canonical tones from words_json)
- `went_green(db, drill_session_id: int, segment_id: int, targets: list[int]) -> bool`
- `build_queue(db, cfg: DrillCfg, kind: str, key: str) -> list[tuple[Segment, list[int]]]`
- `queue_from_ids(db, segment_ids: list[int], kind: str, key: str) -> list[tuple[Segment, list[int]]]`
- Routes: `POST /drill/sessions` body `{kind, key, segment_ids?: list[int]}` → 201 `{id, kind, key, label, short, items: [{segment: SegmentOut, lesson_id, lesson_title, targets}]}` (404 `"no sentences contain this focus"` when empty; 400 for an unknown kind or a malformed key); `PATCH /drill/sessions/{id}` `{ended: true}` → the session dict (404 unknown).

- [ ] **Step 1: Failing tests** — `backend/tests/test_drill_queue.py`:
```python
import pytest
from sqlmodel import Session
from shadow.config import DrillCfg
from shadow.drill.queue import build_queue, queue_from_ids, targets_for, went_green
from shadow.store.models import Attempt, DrillSession, Lesson, Segment, SyllableScore


def syl(ch, tone):
    return {"ch": ch, "pinyin": ch, "pinyin_toneless": ch, "tone": tone}


def seg(db, lesson, idx, tones, text=None, clip=True):
    chars = text or "".join(chr(0x4E00 + idx * 20 + i) for i in range(len(tones)))
    s = Segment(lesson_id=lesson.id, idx=idx, start_s=idx, end_s=idx + 1, text=chars, clip_wav_path="c.wav" if clip else None,
                words_json=[{"word": chars, "pinyin": "", "tones": tones, "char_from": 0, "char_to": len(chars),
                             "syllables": [syl(c, t) for c, t in zip(chars, tones)]}])
    db.add(s); db.commit(); db.refresh(s); return s


def lesson(db, status="ready"):
    les = Lesson(title="L", source_type="upload", status=status); db.add(les); db.commit(); db.refresh(les); return les


@pytest.fixture
def db(client):
    with Session(client.app.state.engine) as s:
        yield s


def test_targets_for():
    s = [syl("a", 3), syl("b", 3), syl("c", 4), syl("在", 4)]
    assert targets_for(s, "tone", "3") == [0, 1]
    assert targets_for(s, "pair", "3-3") == [1]
    assert targets_for(s, "pair", "3-4") == [2]
    assert targets_for(s, "char", "在") == [3]


def test_queue_contains_focus_respects_length_and_cap(db):
    l1, l2 = lesson(db), lesson(db)
    for i in range(6):
        seg(db, l1, i, [3, 3, 1, 2, 4])                 # 2 targets each
    for i in range(3):
        seg(db, l2, i, [1, 3, 1, 2])                    # 1 target each
    seg(db, l2, 3, [3, 3, 1])                           # too short (3 syllables)
    seg(db, l2, 4, [1, 2, 1, 2, 4])                     # no target
    q = build_queue(db, DrillCfg(queue_size=6), "tone", "3")      # l1 ranks higher (2 targets) but is capped at 4
    lessons = [s.lesson_id for s, _ in q]
    assert len(q) == 6 and lessons.count(l1.id) == 4 and lessons.count(l2.id) == 2
    assert all(t for _, t in q) and [(s.lesson_id, s.idx) for s, _ in q] == sorted((s.lesson_id, s.idx) for s, _ in q)


def test_queue_fills_beyond_the_cap_when_no_other_lesson_has_material(db):
    l1 = lesson(db)
    for i in range(6):
        seg(db, l1, i, [3, 1, 2, 4])
    assert len(build_queue(db, DrillCfg(), "tone", "3")) == 6


def test_queue_skips_lessons_that_are_not_ready_and_segments_without_clips(db):
    seg(db, lesson(db, status="processing"), 0, [3, 1, 2, 4])
    seg(db, lesson(db), 0, [3, 1, 2, 4], clip=False)
    assert build_queue(db, DrillCfg(), "tone", "3") == []


def test_recently_green_sentences_are_skipped(db):
    l1 = lesson(db)
    a, b = seg(db, l1, 0, [3, 1, 2, 4]), seg(db, l1, 1, [3, 1, 2, 4])
    ds = DrillSession(kind="tone", key="3", label="x", items_json=[{"segment_id": a.id, "targets": [0]}], ended_at=None)
    db.add(ds); db.commit()
    att = Attempt(segment_id=a.id, mode="drill", audio_path="x.wav", duration_s=1, drill_session_id=ds.id,
                  score_json={"overall": 0.9}); db.add(att); db.commit()
    db.add(SyllableScore(attempt_id=att.id, segment_id=a.id, idx=0, ch="x", pinyin_toneless="x", tone=3, target_tone=3,
                         tone_score=0.9, status="ok")); db.commit()
    assert went_green(db, ds.id, a.id, [0])
    assert [s.id for s, _ in build_queue(db, DrillCfg(), "tone", "3")] == [b.id]


def test_session_from_segment_ids(client, db):
    l1 = lesson(db)
    a = seg(db, l1, 0, [3, 1, 2, 4])
    assert [s.id for s, _ in queue_from_ids(db, [a.id, 9999], "tone", "3")] == [a.id]
    r = client.post("/drill/sessions", json={"kind": "tone", "key": "3", "segment_ids": [9999]})
    assert r.status_code == 404


def test_session_endpoints(client, db):
    l1 = lesson(db)
    seg(db, l1, 0, [3, 1, 2, 4])
    r = client.post("/drill/sessions", json={"kind": "tone", "key": "3"})
    assert r.status_code == 201
    body = r.json()
    assert body["label"] == "tone 3 (low)" and body["short"] is True and body["items"][0]["targets"] == [0]
    assert body["items"][0]["lesson_title"] == "L" and body["items"][0]["segment"]["id"]
    assert client.post("/drill/sessions", json={"kind": "tone", "key": "0"}).status_code == 400
    assert client.post("/drill/sessions", json={"kind": "char", "key": "龘"}).status_code == 404
    ended = client.patch(f"/drill/sessions/{body['id']}", json={"ended": True}).json()
    assert ended["ended_at"] is not None
    assert client.patch("/drill/sessions/9999", json={"ended": True}).status_code == 404
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement `backend/shadow/drill/queue.py`**
```python
"""The drill queue (Phase 3b spec §2): sentences from every ready lesson that contain the focus."""
from __future__ import annotations
from sqlmodel import Session, select
from shadow.api.lessons import _attempt_stats
from shadow.config import DrillCfg
from shadow.scoring.reference import segment_syllables
from shadow.store.models import Attempt, DrillSession, Lesson, Segment, SyllableScore


def targets_for(syllables: list[dict], kind: str, key: str) -> list[int]:
    """Indexes of the syllables the focus is about, by canonical tone (good enough for picking sentences)."""
    if kind == "tone":
        return [i for i, s in enumerate(syllables) if str(s["tone"]) == key]
    if kind == "pair":
        p, t = key.split("-")
        return [i for i in range(1, len(syllables))
                if str(syllables[i - 1]["tone"]) == p and str(syllables[i]["tone"]) == t]
    return [i for i, s in enumerate(syllables) if s["ch"] == key]


def went_green(db: Session, drill_session_id: int, segment_id: int, targets: list[int]) -> bool:
    """Some drill take of this sentence in that session had every target syllable ok."""
    atts = db.exec(select(Attempt.id).where(Attempt.drill_session_id == drill_session_id,
                                            Attempt.segment_id == segment_id)).all()
    for aid in atts:
        rows = {r.idx: r.status for r in db.exec(select(SyllableScore).where(SyllableScore.attempt_id == aid)).all()}
        if targets and all(rows.get(i) == "ok" for i in targets):
            return True
    return False


def _recent_green(db: Session, kind: str, key: str) -> set[int]:
    sessions = db.exec(select(DrillSession).where(DrillSession.kind == kind, DrillSession.key == key)
                       .order_by(DrillSession.started_at.desc(), DrillSession.id.desc()).limit(2)).all()
    out = set()
    for ds in sessions:
        for it in ds.items_json or []:
            if went_green(db, ds.id, it["segment_id"], it["targets"]):
                out.add(it["segment_id"])
    return out


def _candidates(db: Session, cfg: DrillCfg, kind: str, key: str) -> list[tuple[Segment, list[int]]]:
    q = (select(Segment).join(Lesson, Lesson.id == Segment.lesson_id)
         .where(Lesson.status == "ready", Segment.words_json.is_not(None), Segment.clip_wav_path.is_not(None)))
    out = []
    for s in db.exec(q).all():
        syl = segment_syllables(s)
        if cfg.min_syllables <= len(syl) <= cfg.max_syllables and (t := targets_for(syl, kind, key)):
            out.append((s, t))
    return out


def build_queue(db: Session, cfg: DrillCfg, kind: str, key: str) -> list[tuple[Segment, list[int]]]:
    skip = _recent_green(db, kind, key)
    cands = [(s, t) for s, t in _candidates(db, cfg, kind, key) if s.id not in skip]
    stats = _attempt_stats(db, Segment.id.in_([s.id for s, _ in cands])) if cands else {}

    def rank(item):
        s, t = item
        n, last, _ = stats.get(s.id, (0, None, None))
        practised = 2 * (1 - last) if last is not None else (1.0 if n == 0 else 0.0)
        return (-(2 * min(len(t), 3) + practised), s.id)

    ranked = sorted(cands, key=rank)
    taken, deferred, per_lesson = [], [], {}
    for item in ranked:
        if len(taken) == cfg.queue_size:
            break
        lid = item[0].lesson_id
        if per_lesson.get(lid, 0) < cfg.max_per_lesson:
            taken.append(item); per_lesson[lid] = per_lesson.get(lid, 0) + 1
        else:
            deferred.append(item)
    taken += deferred[: cfg.queue_size - len(taken)]          # only lessons without more material left: fill up
    return sorted(taken, key=lambda it: (it[0].lesson_id, it[0].idx))


def queue_from_ids(db: Session, segment_ids: list[int], kind: str, key: str) -> list[tuple[Segment, list[int]]]:
    out = []
    for sid in segment_ids:
        s = db.get(Segment, sid)
        if s is not None and (t := targets_for(segment_syllables(s), kind, key)):
            out.append((s, t))
    return out
```
Check `_attempt_stats`' signature in api/lessons.py (it takes `*where` conditions on the attempt query — pass a condition that restricts to these segments, e.g. `Attempt.segment_id.in_(…)`, matching how it is used there; adjust the call accordingly).

In `api/drill.py` add:
```python
class SessionIn(BaseModel):
    kind: str
    key: str
    segment_ids: list[int] | None = None


class SessionPatch(BaseModel):
    ended: bool = False


def _valid(kind: str, key: str) -> bool:
    if kind == "tone":
        return key in {"1", "2", "3", "4"}
    if kind == "pair":
        parts = key.split("-")
        return len(parts) == 2 and all(p in {"1", "2", "3", "4"} for p in parts)
    return kind == "char" and len(key) == 1 and is_hanzi(key)


@router.post("/drill/sessions", status_code=201)
def create_drill(body: SessionIn, request: Request, db: Session = Depends(get_session)):
    if not _valid(body.kind, body.key):
        raise HTTPException(400, "bad focus")
    cfg = request.app.state.settings.drill
    items = (queue_from_ids(db, body.segment_ids, body.kind, body.key) if body.segment_ids is not None
             else build_queue(db, cfg, body.kind, body.key))
    if not items:
        raise HTTPException(404, "no sentences contain this focus")
    pinyin = next((s["pinyin_toneless"] for seg, t in items for i, s in enumerate(segment_syllables(seg)) if i in t), None)
    ds = DrillSession(kind=body.kind, key=body.key, label=focus_label(body.kind, body.key, pinyin if body.kind == "char" else None),
                      items_json=[{"segment_id": s.id, "targets": t} for s, t in items])
    db.add(ds); db.commit(); db.refresh(ds)
    return {"id": ds.id, "kind": ds.kind, "key": ds.key, "label": ds.label, "short": len(items) < cfg.queue_size,
            "items": [{"segment": _segment_out(db, s), "lesson_id": s.lesson_id,
                       "lesson_title": db.get(Lesson, s.lesson_id).title, "targets": t} for s, t in items]}


@router.patch("/drill/sessions/{session_id}")
def end_drill(session_id: int, body: SessionPatch, db: Session = Depends(get_session)):
    ds = db.get(DrillSession, session_id)
    if ds is None:
        raise HTTPException(404, "drill session not found")
    if body.ended and ds.ended_at is None:
        ds.ended_at = datetime.now(timezone.utc); db.add(ds); db.commit(); db.refresh(ds)
    return {"id": ds.id, "kind": ds.kind, "key": ds.key, "label": ds.label, "started_at": ds.started_at, "ended_at": ds.ended_at}
```
(Imports: `datetime, timezone`, `BaseModel`, `HTTPException`, `is_hanzi`, `focus_label`, `build_queue`, `queue_from_ids`, `segment_syllables`, `_segment_out`, `Lesson`, `DrillSession`.)

- [ ] **Step 4: All backend tests → PASS; commit** `feat(backend): drill queue across lessons and drill sessions`

---

### Task 4: Summaries — `GET /drill/sessions/{id}/summary`, `GET /drill/sessions`

**Files:** Create `backend/shadow/drill/summary.py`; Modify `backend/shadow/api/drill.py`; Test append to `backend/tests/test_drill_queue.py` (or a new `test_drill_summary.py`).

**Interfaces — Produces:**
- `target_mean(rows: dict[int, tuple[str, float | None]], targets: list[int]) -> tuple[float | None, int]` — (mean over targets with missing = 0 and unvoiced/absent ignored, number of targets with status ok)
- `session_summary(db, ds: DrillSession) -> dict` — the shape in spec §3 (`items`, `first_mean`, `best_mean`, `green_first`, `green_best`, `n_targets`, `history`)
- Routes: `GET /drill/sessions/{id}/summary` (404 unknown); `GET /drill/sessions?limit=10` → `{"sessions": [{id, kind, key, label, started_at, ended_at, first_mean, best_mean}]}` newest first (ended sessions only).

- [ ] **Step 1: Failing tests**
```python
def _drill_take(db, ds, seg_id, statuses_scores, overall=0.5):
    att = Attempt(segment_id=seg_id, mode="drill", audio_path="x.wav", duration_s=1, drill_session_id=ds.id,
                  score_json={"overall": overall}); db.add(att); db.commit()
    for i, (st, sc) in enumerate(statuses_scores):
        db.add(SyllableScore(attempt_id=att.id, segment_id=seg_id, idx=i, ch="x", pinyin_toneless="x", tone=3,
                             target_tone=3, tone_score=sc, status=st))
    db.commit(); return att


def test_target_mean():
    from shadow.drill.summary import target_mean
    rows = {0: ("ok", 0.9), 1: ("missing", None), 2: ("unvoiced", None), 3: ("close", 0.5)}
    assert target_mean(rows, [0, 1, 2]) == (pytest.approx(0.45), 1)
    assert target_mean(rows, [2]) == (None, 0)


def test_summary_first_best_tries_and_history(client, db):
    l1 = lesson(db)
    a = seg(db, l1, 0, [3, 1, 3, 4])
    ds = DrillSession(kind="tone", key="3", label="tone 3 (low)", items_json=[{"segment_id": a.id, "targets": [0, 2]}])
    db.add(ds); db.commit(); db.refresh(ds)
    _drill_take(db, ds, a.id, [("close", 0.4), ("ok", 0.9), ("close", 0.5), ("ok", 0.9)])
    gated = Attempt(segment_id=a.id, mode="drill", audio_path="x.wav", duration_s=1, drill_session_id=ds.id,
                    score_json={"overall": None, "warnings": ["too_quiet"]}); db.add(gated); db.commit()
    best = _drill_take(db, ds, a.id, [("ok", 0.8), ("ok", 0.9), ("ok", 0.9), ("ok", 0.9)])
    client.patch(f"/drill/sessions/{ds.id}", json={"ended": True})
    s = client.get(f"/drill/sessions/{ds.id}/summary").json()
    it = s["items"][0]
    assert it["tries"] == 2 and it["went_green"] is True and it["best"]["attempt_id"] == best.id
    assert it["first"]["mean"] == pytest.approx(0.45) and it["first"]["green"] == 0 and it["best"]["green"] == 2
    assert s["first_mean"] == pytest.approx(0.45) and s["best_mean"] == pytest.approx(0.85) and s["n_targets"] == 2
    assert [h["session_id"] for h in s["history"]] == [ds.id]
    assert client.get("/drill/sessions").json()["sessions"][0]["best_mean"] == pytest.approx(0.85)


def test_summary_skips_deleted_segments(client, db):
    ds = DrillSession(kind="tone", key="3", label="x", items_json=[{"segment_id": 9999, "targets": [0]}])
    db.add(ds); db.commit(); db.refresh(ds)
    assert client.get(f"/drill/sessions/{ds.id}/summary").json()["items"] == []
    assert client.get("/drill/sessions/9999/summary").status_code == 404
```

- [ ] **Step 2: Run → FAIL**

- [ ] **Step 3: Implement `backend/shadow/drill/summary.py`**
```python
"""Drill summaries (Phase 3b spec §3): first and best take per sentence, totals, and the focus's history."""
from __future__ import annotations
from sqlmodel import Session, select
from shadow.store.models import Attempt, DrillSession, Lesson, Segment, SyllableScore


def target_mean(rows: dict[int, tuple[str, float | None]], targets: list[int]) -> tuple[float | None, int]:
    vals, green = [], 0
    for i in targets:
        status, score = rows.get(i, ("unvoiced", None))
        if status == "unvoiced":
            continue
        vals.append(0.0 if status == "missing" else (score or 0.0))
        green += status == "ok"
    return (sum(vals) / len(vals) if vals else None), green


def _takes(db: Session, ds: DrillSession, segment_id: int, targets: list[int]) -> list[dict]:
    """Scored drill takes of the sentence in this session, oldest first, with their target mean and green count."""
    atts = db.exec(select(Attempt).where(Attempt.drill_session_id == ds.id, Attempt.segment_id == segment_id)
                   .order_by(Attempt.created_at, Attempt.id)).all()
    out = []
    for a in atts:
        if not a.score_json or a.score_json.get("overall") is None:
            continue
        rows = {r.idx: (r.status, r.tone_score) for r in db.exec(select(SyllableScore).where(SyllableScore.attempt_id == a.id)).all()}
        mean, green = target_mean(rows, targets)
        out.append({"attempt_id": a.id, "mean": mean, "green": green})
    return out


def _mean(xs: list[float | None]) -> float | None:
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def _totals(db: Session, ds: DrillSession) -> dict:
    items = []
    for it in ds.items_json or []:
        seg = db.get(Segment, it["segment_id"])
        if seg is None:
            continue
        takes = _takes(db, ds, seg.id, it["targets"])
        first = takes[0] if takes else None
        best = max(takes, key=lambda t: (t["mean"] if t["mean"] is not None else -1)) if takes else None
        items.append({"segment_id": seg.id, "lesson_id": seg.lesson_id, "lesson_title": db.get(Lesson, seg.lesson_id).title,
                      "idx": seg.idx, "text": seg.text, "targets": it["targets"], "tries": len(takes), "first": first, "best": best,
                      "went_green": any(t["green"] == len(it["targets"]) for t in takes)})
    tried = [i for i in items if i["tries"]]
    return {"items": items,
            "first_mean": _mean([i["first"]["mean"] for i in tried]), "best_mean": _mean([i["best"]["mean"] for i in tried]),
            "green_first": sum(i["first"]["green"] for i in tried), "green_best": sum(i["best"]["green"] for i in tried),
            "n_targets": sum(len(i["targets"]) for i in tried)}


def session_summary(db: Session, ds: DrillSession) -> dict:
    tot = _totals(db, ds)
    past = db.exec(select(DrillSession).where(DrillSession.kind == ds.kind, DrillSession.key == ds.key,
                                              DrillSession.ended_at.is_not(None))
                   .order_by(DrillSession.started_at.desc(), DrillSession.id.desc()).limit(10)).all()
    history = []
    for p in reversed(past):
        t = tot if p.id == ds.id else _totals(db, p)
        history.append({"session_id": p.id, "started_at": p.started_at, "first_mean": t["first_mean"], "best_mean": t["best_mean"]})
    return {"id": ds.id, "kind": ds.kind, "key": ds.key, "label": ds.label, **tot, "history": history}


def recent_sessions(db: Session, limit: int) -> list[dict]:
    out = []
    for ds in db.exec(select(DrillSession).where(DrillSession.ended_at.is_not(None))
                      .order_by(DrillSession.ended_at.desc(), DrillSession.id.desc()).limit(limit)).all():
        t = _totals(db, ds)
        out.append({"id": ds.id, "kind": ds.kind, "key": ds.key, "label": ds.label, "started_at": ds.started_at,
                    "ended_at": ds.ended_at, "first_mean": t["first_mean"], "best_mean": t["best_mean"]})
    return out
```
Routes in `api/drill.py`: `GET /drill/sessions/{session_id}/summary` → `session_summary` (404 unknown); `GET /drill/sessions` with `limit: int = Query(10, ge=1, le=50)` → `{"sessions": recent_sessions(db, limit)}`.

- [ ] **Step 4: All backend tests → PASS; commit** `feat(backend): drill summaries and recent drills`

---

### Task 5: Frontend API types and the drill step machine

**Files:** Modify `frontend/src/api/types.ts`, `frontend/src/api/client.ts`; Create `frontend/src/lib/drill.ts`, `frontend/src/lib/drill.test.ts`.

**Interfaces — Produces:**
- types: `DrillFocus { kind: 'tone' | 'pair' | 'char'; key: string; label: string; mean: number; n: number }`; `DrillItem { segment: Segment; lesson_id: number; lesson_title: string; targets: number[] }`; `DrillSession { id: number; kind: string; key: string; label: string; short: boolean; items: DrillItem[] }`; `DrillTake { attempt_id: number; mean: number | null; green: number }`; `DrillSummaryItem { segment_id; lesson_id; lesson_title; idx; text; targets: number[]; tries: number; first: DrillTake | null; best: DrillTake | null; went_green: boolean }`; `DrillSummary { id; kind; key; label; items: DrillSummaryItem[]; first_mean: number | null; best_mean: number | null; green_first: number; green_best: number; n_targets: number; history: { session_id: number; started_at: string; first_mean: number | null; best_mean: number | null }[] }`; `DrillRecent { id; kind; key; label; started_at; ended_at; first_mean; best_mean }`.
- client: `api.drill.focuses(): Promise<{ focuses: DrillFocus[]; auto: { kind: string; key: string } | null }>`; `api.drill.start(body: { kind: string; key: string; segment_ids?: number[] }): Promise<DrillSession>`; `api.drill.end(id): Promise<unknown>`; `api.drill.summary(id): Promise<DrillSummary>`; `api.drill.recent(limit = 10): Promise<DrillRecent[]>`; `api.segments.postAttempt` opts gain `drill_session_id?: number` (appended to the form when set); `Mode` gains `'drill'`.
- `lib/drill.ts`: 
```ts
export type DrillStep = 'listen' | 'record' | 'review' | 'done'
export type Outcome = 'retry' | 'next'
export interface DrillState { i: number; n: number; step: DrillStep; tries: number; outcome: Outcome | null }
export const startDrill = (n: number): DrillState
export const listened = (s: DrillState): DrillState            // listen → record
export function scored(s: DrillState, r: { gated: boolean; allGreen: boolean }, maxTries: number): DrillState
export const advance = (s: DrillState): DrillState              // review → record (retry) or next item's listen / done
export const skip = (s: DrillState): DrillState                 // any step → next item's listen / done
export function targetsGreen(score: Score | null | undefined, targets: number[]): boolean
```

- [ ] **Step 1: Failing tests** — `frontend/src/lib/drill.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import type { Score } from '../api/types'
import { advance, listened, scored, skip, startDrill, targetsGreen } from './drill'

const sc = (statuses: string[]): Score => ({ overall: 0.5, tone_overall: 0.5, segmental_overall: null, rate_ratio: 1, ref_contour: null, usr_contour: null, warnings: [],
  syllables: statuses.map((s) => ({ ch: 'x', pinyin: 'x', tone: 3, target_tone: 3, heard_tone: 3, status: s as never, tone_score: 0.5, p_target: 0.5, contour: 0.5 })) })

describe('drill steps', () => {
  it('listen → record → review → next when the targets are green', () => {
    let s = listened(startDrill(2))
    expect(s.step).toBe('record')
    s = scored(s, { gated: false, allGreen: true }, 3)
    expect(s).toMatchObject({ step: 'review', tries: 1, outcome: 'next' })
    s = advance(s)
    expect(s).toMatchObject({ i: 1, step: 'listen', tries: 0, outcome: null })
  })
  it('retries until the cap, then moves on', () => {
    let s = listened(startDrill(1))
    s = scored(s, { gated: false, allGreen: false }, 3); expect(s.outcome).toBe('retry')
    s = advance(s); expect(s.step).toBe('record')
    s = scored(s, { gated: false, allGreen: false }, 3); s = advance(s)
    s = scored(s, { gated: false, allGreen: false }, 3)
    expect(s).toMatchObject({ tries: 3, outcome: 'next' })
    expect(advance(s).step).toBe('done')
  })
  it('a gate warning does not count as a try', () => {
    const s = scored(listened(startDrill(1)), { gated: true, allGreen: false }, 3)
    expect(s).toMatchObject({ tries: 0, outcome: 'retry', step: 'review' })
  })
  it('skip goes to the next sentence from any step, and ends after the last', () => {
    expect(skip(startDrill(2))).toMatchObject({ i: 1, step: 'listen' })
    expect(skip({ ...startDrill(1), step: 'record' }).step).toBe('done')
  })
  it('targets are green only when every target syllable is ok', () => {
    expect(targetsGreen(sc(['ok', 'close', 'ok']), [0, 2])).toBe(true)
    expect(targetsGreen(sc(['ok', 'close', 'ok']), [0, 1])).toBe(false)
    expect(targetsGreen({ ...sc(['ok']), overall: null, warnings: ['too_quiet'] }, [0])).toBe(false)
    expect(targetsGreen(null, [0])).toBe(false)
  })
})
```

- [ ] **Step 2: Run → FAIL**; **Step 3: Implement** types, client and `lib/drill.ts` (pure functions, no React; `targetsGreen` returns false when `score?.overall == null` or a target index is out of range); **Step 4: frontend checks → PASS; commit** `feat(frontend): drill API client and step machine`

---

### Task 6: The Drill page — start screen

**Files:** Create `frontend/src/pages/Drill.tsx`, `frontend/src/pages/Drill.test.tsx`; Modify `frontend/src/App.tsx` (route `/drill`), `frontend/src/components/Shell.tsx` (nav tab "Drill" after Review).

**Behaviour (spec §4):** on mount `api.drill.focuses()` and `api.drill.recent(1)`. Show "Today's focus" = the `auto` focus (label, "your mean NN · n syllables"), then up to two alternatives (the next focuses in list order, excluding auto), each with a **Start** button; the last ended drill as "Last drill: <label> · <first→best>" with a "See summary" button. Query params `?kind=&key=` (from Stats) start that focus immediately (skip the start screen). Empty `focuses` → "Practise a few sentences first — drills start once there's enough to know your weak spots." with a link to the Library. A 404 from `start` shows its message ("No sentences contain this focus yet."). Start → `api.drill.start({kind, key})` → hand the session to the runner (Task 7) — in this task render a placeholder `<DrillRunner session={...} />` stub that shows the queue length, to be filled in Task 7.

**Tests (`Drill.test.tsx`, mock `../api/client` like Stats.test does):** shows the auto focus with mean and alternatives; Start calls `api.drill.start` with that focus; `?kind=pair&key=3-3` starts immediately; empty state; 404 message; Shell has a "Drill" tab linking to `/drill`.

**Commit:** `feat(frontend): Drill page start screen and navigation`

---

### Task 7: The Drill page — runner (per sentence) and summary

**Files:** Modify `frontend/src/pages/Drill.tsx`; Create `frontend/src/components/DrillSummary.tsx` (+ test); Test `frontend/src/pages/Drill.test.tsx`.

**Runner behaviour (spec §4), built from `lib/drill.ts` and the Practice building blocks:**
- Top bar: focus label · "Sentence i+1 / N" · "Try t / maxTries" (maxTries = 3; read it from a constant mirroring the backend default) · lesson title of the current item · "Finish".
- `listen` step: the item's clip (`api.segments.audioUrl(segment.id)`) plays once at the guide level (`useSettings().guideLevel × referenceVolume`, as Practice's chorus does) with the karaoke wipe (`clipSpans`/`stageWipe` as in Practice) over `KaraokeSentence`; CueLine shows "Listen and speak along"; Enter skips to record; when playback ends → `listened`.
- `record` step: CueLine "Your turn — Enter to record"; Enter starts the mic (`useMic().open()`), Enter stops (`finish()`); takes shorter than `MIN_TAKE_S` are dropped with the same message as Practice; text hidden while recording when `practice.hideTextWhileRecording`; then `toWav16k` → `api.segments.postAttempt(segment.id, wav, { mode: 'drill', drill_session_id })`; meanwhile reference then take play back (`playSequence`); on the response → `scored(state, { gated: score.overall == null, allGreen: targetsGreen(score, targets) }, 3)`.
- `review` step: `TwoTrack` with the take's score (as Practice passes it) and `scoreHeader`, plus the **target syllables outlined** — add an optional `highlight?: number[]` prop to `TwoTrack`/`CellRow` that adds `ring-2 ring-accent` to those cells (both rows); hint line = `warningText(score) ?? noticeText(score)`; buttons/keys: Enter = "Again" when outcome is retry / "Next" when next (calls `advance`); "→" = `skip`; "R" replays the take; an upload error (incl. the 409 rebuild message) shows in the hint line and leaves the state at `record` without counting a try.
- `done` (or Finish, or after the last item): `api.drill.end(id)` then `api.drill.summary(id)` → `DrillSummary`.
- Unmount mid-drill: `api.drill.end(id)` (best effort, errors ignored), stop audio, abandon the mic (same cleanup pattern as Practice).
- Reuse `VolumeSliders` (reference + guide) and `HelpOverlay`-style key hints are optional (YAGNI: a one-line key legend under the transport is enough).

**`DrillSummary` (props `summary: DrillSummary`, `onAgain(segmentIds: number[])`, `onDone()`):** headline "<label>: target syllables first try NN → best NN · green F → B of T"; a small history line (SVG or a row of numbers is fine — reuse `ToneTrend` styling conventions: dark palette, `role="img"`, aria-label "Drill history for <label>"); list of sentences that never went green, each with "Open in Practice" (`/practice/<lesson_id>?idx=<idx>`); "Drill these again" → `onAgain(ids)` → `api.drill.start({kind, key, segment_ids})` and a new run; "Done" → back to the start screen.

**Tests (`Drill.test.tsx`, mocks as Practice.test does for player/recorder/TwoTrack):**
1. listen → record → upload with `mode: 'drill'` and `drill_session_id`; a score with all targets ok → "Next" moves to sentence 2/N.
2. targets not green → "Again" → second take; after the 3rd non-green take → "Next".
3. a gate-warning take (overall null) shows the warning and the try counter stays.
4. TwoTrack receives `highlight` = the item's targets.
5. finishing shows the summary (mock `api.drill.summary`), "Drill these again" calls `api.drill.start` with `segment_ids`.
6. unmount mid-drill calls `api.drill.end`.
`DrillSummary.test.tsx`: headline numbers, never-green list with Practice links, history aria-label.

**Commit(s):** `feat(frontend): drill runner with retry-until-green` and `feat(frontend): drill summary with history and drill-again`

---

### Task 8: Entry points — Stats "Drill this", Drills panel, Practice `?idx=`

**Files:** Modify `frontend/src/pages/Stats.tsx` (+ test), `frontend/src/components/ToneMatrix.tsx` (+ test), `frontend/src/pages/Practice.tsx` (+ test).

- Stats: a small "Drill this" button on each per-tone row (kind `tone`, key `t`, tones 1–4 only), each character row (kind `char`, key `ch`), and in `ToneMatrix` cells with data where both tones are 1–4 (kind `pair`, key `p-t`; the cell becomes a button/link with an accessible name "Drill tone pair p→t"). All navigate to `/drill?kind=…&key=…`.
- Stats: a **Drills** panel from `api.drill.recent(10)`: label, date, "first → best" (pct), or "No drills yet."
- Practice: read `idx` from the URL search params once the lesson has loaded; if it is an integer within range, `setIdx(idx)` (0-based, matching `segment.idx` order in the lesson). One test: `/practice/1?idx=1` opens on the second sentence.
- Tests for each.

**Commit:** `feat(frontend): drill entry points on Stats; Practice opens at ?idx=`

---

### Task 9: Docs and acceptance

**Files:** Modify `README.MD` (a "Drills" section under what it does; roadmap: Phase 3b built, 3a waiting on the check set); create `docs/phase3b-acceptance.md`:
```markdown
# Phase 3b acceptance — drills

- [ ] Drill tab: today's focus shows a tone, tone pair or character with your mean; two alternatives are offered.
- [ ] Start: the first sentence plays once while you speak along, then you record; the target syllables are outlined.
- [ ] A take with all targets green moves on; otherwise "Again", at most 3 scored tries; a too-quiet take does not count.
- [ ] Sentences come from more than one lesson when your lessons have material.
- [ ] Finish: the summary shows first → best on the target syllables and the history for this focus; "Drill these again" works; "Open in Practice" opens that sentence.
- [ ] Stats: "Drill this" on a tone, a tone-pair cell and a character starts that drill; the Drills panel lists your drills.
- [ ] A second drill the same day does not offer the same focus first when another is about as weak.
```
Run `make test` (all green) and commit `docs: Phase 3b drills in the README and acceptance checklist`.

---

## Ledger

Record rulings, deviations and test totals here, with dates.
