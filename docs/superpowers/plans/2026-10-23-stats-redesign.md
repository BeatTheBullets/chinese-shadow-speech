# Stats redesign — overview widgets, three scores, details pages — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the long Stats page with an overview of three 0–100 scores (Characters, Tones, Sounds), top-3 widgets, a Flow-only widget and a second row, each opening a details page.

**Architecture:**
- **Backend.** The score rules of spec §2 live in one pure module, `backend/shadow/stats/scores.py`. It works on plain row objects and is unit-tested on hand-made rows. `backend/shadow/api/stats.py` loads rows from the DB (30-day window, optional Flow filter) and serves `/api/stats/overview` plus one endpoint per details page.
- **Frontend.** `/stats` becomes an overview page. Each area gets a details page under `frontend/src/pages/stats/`. They share a few parts in `frontend/src/components/stats/` (score card, widget, details header) and pure display helpers in `frontend/src/lib/statsView.ts`.

**Tech Stack:** FastAPI + SQLModel (SQLite), pytest; React 18, react-router 6, Tailwind 3 with the Lacquer tokens, vitest 3 + Testing Library.

**Spec:** `docs/superpowers/specs/2026-10-22-stats-redesign-design.md`. Read it first; §n refers to it. The look comes from `docs/superpowers/specs/2026-10-22-app-style-design.md`, which is already built.

**One deviation from the spec (decided while planning).** Spec §3 names the pages `/stats/characters`, `/stats/tones`, … and §4 names API endpoints with the same paths. In the packaged app the backend serves both the API and the SPA from one origin, and API routes win. A reload or bookmark of `/stats/tones` would then show raw JSON. So **every stats JSON endpoint moves to `/api/stats/...`**, and the page paths stay as the spec wrote them. `/lessons/{id}/stats` is not a page path and stays where it is.

## Global Constraints

- **Window:** all scores, lists and details rows use the last 30 days of attempts (`now - 30 days`, rolling). The change compares `[now-7d, now)` with `[now-14d, now-7d)`. The Tones weekly trend and the Sounds sparklines keep their 12 weeks.
- **Which takes count:** every take (`echo`, `chorus`, `guided`, `flow`, `drill`). The exception is the Flow scores and `?mode=flow`, which use `Attempt.mode == "flow"` only.
- **Thresholds (verbatim from the spec):**
  - a Tones or Sounds score needs ≥ 30 counted syllables, else "—"
  - a Characters score needs ≥ 10 qualifying characters, else "—"
  - a character qualifies with ≥ 3 takes
  - a character in the widget needs ≥ 8 takes
  - a tone or tone pair in the widget needs ≥ 8 rows
  - a sound direction needs ≥ 8 chances
  - regressed means best − last ≥ 0.15
  - the change shows only when both 7-day values exist
- **One tone-mean rule everywhere:** `unvoiced` rows are left out; `missing` rows count 0.0 (their `tone_score` may be NULL); other rows use `tone_score` and are skipped when it is NULL. The tone is `coalesce(target_tone, tone)`.
- **Card copy (verbatim, §2):**
  - Characters: "Share of your takes where both tone and sound were right, averaged over the characters you've practised (≥ 3 times, last 30 days)."
  - Tones: "Your average tone score over all scored syllables in the last 30 days (neutral tone left out)."
  - Sounds: "Share of syllables said right among the hard sounds — zh/ch/sh vs z/c/s, r vs l, ü vs u, -n vs -ng and the vowel pairs ou/uo, an/en, ang/eng; last 30 days. f/h is left out."
  - Sounds details footer: "Not checked yet: j/q/x mix-ups and breathy vs plain consonants (b/p, d/t, g/k, j/q, zh/ch, z/c)."
  - Empty overview: "Practise a few sentences to see your scores."
- **Scores travel as 0..1** in the API, like every other score. The frontend shows `Math.round(v * 100)`.
- **Style:**
  - Lacquer tokens only, with no hex literals in components.
  - Main cards (score cards, widgets, details panels) use `<Card notched>`.
  - Characters use `font-hanzi`.
  - Bars and rings use `accent` on a `line` track.
  - Small text uses `fgdim`.
- **Drill links** stay exactly as today: `/drill?kind=<kind>&key=<encodeURIComponent(key)>`. **Practice links:** `/practice/<lesson_id>?idx=<idx>` (Practice already reads `idx`).
- **Commands** (run from the fresh clone, see below):
  - Backend: `cd backend && PYTHONPATH=$PWD ~/shadow-speech/backend/.venv/bin/python -m pytest -q`. **Never** run `uv run` or `uv sync` in the clone: the venv is shared with the user's running backend.
  - Frontend: `cd frontend && npm test -- --run && npx eslint . && npx tsc -b`. One existing Drawer.tsx eslint warning is expected.
- **Where to build and how to commit:**
  - Build in a fresh clone in the session scratchpad, with `frontend/node_modules` symlinked from the main checkout.
  - Set the clone's local identity to `BeatTheBullets <130062727+BeatTheBullets@users.noreply.github.com>`.
  - Push from the clone.
  - No personal names, emails or home paths in files or commit messages.
  - Commits end with a blank line and the Co-Authored-By line of the model that writes them.

## Review Focus

- **Reloading a details page in the packaged app** (`/stats/tones` served by the backend, same origin) must return the SPA's `index.html`, not JSON. Test: Task 2 `test_spa_serves_stats_pages`.
- **SQLite returns naive datetimes.** Splitting rows into the two 7-day windows must neither crash ("can't compare offset-naive and offset-aware") nor misfile a take. Test: Task 3 `test_overview_scores_and_weekly_change`, using rows written through the DB.
- **`?mode=flow` with no Flow takes:** the details endpoints return empty lists and the page shows its empty state. An unknown mode is a 422, not a silent "all takes". Tests: Task 2 `test_mode_filter_flow_only`, Task 6 `flow-only header links back to all takes`.
- **A score of exactly 0, and a week with no data:** 0 must render "0" (not "—", a falsy check). The change must be "—" when either week is null, never "▲ 80". Test: Task 4 `scoreText` and `changeText` cases.
- **A sentence whose only takes in the window are unscored** (`overall` NULL, e.g. a failed scoring) is not listed. Its best-ever can come from a take older than the window. Test: Task 2 `test_sentences_window_last_and_best_ever`.

---

### Task 1: Hard directions and the pure score module

**Files:**
- Modify: `backend/shadow/scoring/sounds/contrasts.py` (add the constant after `DIRECTIONS`)
- Create: `backend/shadow/stats/__init__.py` (empty), `backend/shadow/stats/scores.py`
- Test: `backend/tests/test_stats_scores.py`

**Interfaces:**
- Produces, in `contrasts.py`: `HARD_DIRECTIONS: frozenset[str]`, containing exactly `zh>z z>zh ch>c c>ch sh>s s>sh r>l l>r ü>u u>ü ng>n n>ng ou>uo uo>ou an>en en>an ang>eng eng>ang`. Its comment says why f/h, ai/ei and ao/ou are left out. Sources: Chinese-teaching literature on learner difficulties and a learner study (stats spec §2.3).
- Produces, in `shadow/stats/scores.py`:
  - Constants: `MIN_SYLLABLES = 30`, `MIN_CHARS = 10`, `MIN_CHAR_TAKES = 3`, `MIN_WEAK = 8`, `MIN_CHANCES = 8`, `REGRESSED = 0.15`.
  - `@dataclass(frozen=True) class SylRow`, with fields:
    - `ch: str`
    - `pinyin: str` (toneless, lower case)
    - `tone: int` (already `coalesce(target_tone, tone)`)
    - `prev_tone: int | None`
    - `tone_score: float | None`
    - `status: str`
    - `sound_status: str | None`
    - `heard: str | None` (lower case)
    - `created_at: datetime` (aware UTC)
    - `attempt_id: int`
    - `idx: int`
  - `@dataclass(frozen=True) class Score: value: float | None; n: int`
  - `tone_value(r: SylRow) -> float | None`
  - `char_right(r: SylRow) -> bool | None` returns None when the row does not count: unvoiced, not hanzi (`shadow.ingest.text.is_hanzi`), or tone not 1–4.
  - `sound_outcome(r: SylRow) -> bool | None` returns True for right and False for a hard slip. It returns None when the row does not count: not checked, no hard direction in `checkable_directions_of(pinyin)`, or a slip whose `direction(pinyin, heard)` is not hard (including None).
  - Scores: `tones_score(rows) -> Score`, `characters_score(rows) -> Score`, `sounds_score(rows) -> Score`
  - `score_set(rows: list[SylRow], now: datetime) -> dict` returns `{"characters"|"tones"|"sounds": {"value", "last7", "prev7", "n"}}`. `value` and `n` cover all the rows given; `last7` and `prev7` are the same score's value on each 7-day subset.
  - `character_stats(rows) -> list[dict]` returns dicts `{ch, pinyin, score, tone_right, sound_right, takes, trend}`.
    - Only characters with ≥ 3 takes, sorted by `(score, -takes, ch)`.
    - `pinyin` is toned via `heard_pinyin(toneless, most common tone)`.
    - `tone_right` = share with `status == "ok"`.
    - `sound_right` = ok / checked takes, or None when none were checked.
    - `trend` = mean right over the last 10 takes − mean right over the rest, when takes ≥ 15, else None. Takes are ordered by `(created_at, attempt_id, idx)`.
  - `tone_groups(rows) -> tuple[list[dict], list[dict]]` returns `[{tone, mean, n}]` for tones 0–4 and `[{prev_tone, tone, mean, n}]` for prev 0–4 and tone 0–4. Both use `tone_value`.
  - `weakest_tones(rows, k=3) -> list[dict]` returns `{kind: "tone"|"pair", key, label, mean, n}`, the k lowest by `(mean, -n, key)`. It covers tones 1–4 and pairs with prev 1–4 and tone 0–4, each with ≥ 8 rows. Labels are `"Tone 3"` and `"1 → 0"`; the key is `"3"` or `"1-0"`.
  - `sound_directions(rows) -> list[dict]` returns `{key, label, slips, chances, rate, hard}`, with the same chance and slip semantics as today's `/stats/sounds`. It keeps directions with ≥ 8 chances, sorted by `(-rate, -chances, key)`.
  - `weakest_sounds(rows, k=3) -> list[dict]` returns `sound_directions` filtered to `hard and slips > 0`, first k.
  - `rank_sentences(rows: list[dict]) -> list[dict]` takes dicts that have at least `last` and `best`. It returns them with `regressed: bool` (`best - last >= REGRESSED - 1e-9`, so 0.95/0.80 counts). Regressed rows come first, largest drop first; then the rest by `last` ascending.

- [ ] **Step 1: Write the failing tests** in `backend/tests/test_stats_scores.py`. Add a helper `row(ch="好", py="hao", tone=3, prev=None, score=0.8, status="ok", sound=None, heard=None, days_ago=1, attempt=1, idx=0) -> SylRow`, plus these tests:

```python
def test_hard_directions():
    assert HARD_DIRECTIONS <= set(DIRECTIONS) and len(HARD_DIRECTIONS) == 18
    assert not HARD_DIRECTIONS & {"f>h", "h>f", "ai>ei", "ei>ai", "ao>ou", "ou>ao"}

def test_tone_value_rules():
    assert tone_value(row(status="missing", score=None)) == 0.0
    assert tone_value(row(status="unvoiced")) is None
    assert tone_value(row(score=0.8)) == 0.8

def test_tones_score_leaves_neutral_out_and_counts_missing_as_zero():
    rows = [row(score=1.0)] * 20 + [row(status="missing", score=None)] * 10 + [row(tone=0, score=0.0)] * 5 + [row(status="unvoiced")] * 5
    assert tones_score(rows) == Score(20 / 30, 30)

def test_scores_need_enough_units():
    assert tones_score([row()] * 29) == Score(None, 29)
    assert sounds_score([row(py="chi", sound="ok")] * 29) == Score(None, 29)

def test_char_right_rules():
    assert char_right(row(status="ok", sound=None)) is True       # NULL sound: only the tone decides
    assert char_right(row(status="ok", sound="slip", heard="hou")) is False
    assert char_right(row(status="close")) is False and char_right(row(status="missing", score=None)) is False
    assert char_right(row(status="unvoiced")) is None and char_right(row(tone=0)) is None and char_right(row(ch="A")) is None

def test_characters_score_is_a_mean_over_characters():
    rows = [row(ch="的", py="de", tone=0)] * 50                     # neutral: never counted
    rows += [row(ch="飞", py="fei", tone=1)] * 80                    # 80 takes, all right
    for c in "一二三四五六七八九":                                     # 9 more, 1 of 4 right
        rows += [row(ch=c, tone=1)] + [row(ch=c, tone=1, status="wrong")] * 3
    rows += [row(ch="十", tone=2)] * 2                               # < 3 takes: not qualifying
    assert characters_score(rows) == Score(pytest.approx((1 + 9 * 0.25) / 10), 10)
    assert characters_score(rows[:-2 - 4]).value is None             # 9 qualifying characters

def test_sounds_score_hard_only():
    rows = ([row(py="chi", sound="ok")] * 20 + [row(py="chi", sound="slip", heard="ci")] * 10
            + [row(py="fan", sound="slip", heard="han")] * 5                     # f/h slip: left out entirely
            + [row(py="fan", sound="ok")] * 5 + [row(py="fu", sound="ok")] * 5   # fu offers only f>h: not counted
            + [row(py="chi", sound=None)] * 5)                                   # not checked
    assert sounds_score(rows) == Score(pytest.approx(25 / 35), 35)
```

Also add these tests:
- `test_character_stats_rows`:
  - one character with 20 takes, ordered so that the first 10 are wrong and the last 10 right, gives `trend == 1.0`
  - `sound_right is None` when no take was checked
  - `pinyin == "hǎo"` for 好 with tone 3
  - a 2-take character is absent
  - the list is worst first
- `test_tone_groups_and_weakest_tones`:
  - a pair 1→0 with 8 rows at 0.2 is in `weakest_tones` with label `"1 → 0"` and key `"1-0"`
  - a pair with 7 rows is absent
  - tone 0 alone is never in it
  - `tone_groups` includes tone 0 and pair rows with prev 0
- `test_sound_directions_and_weakest_sounds`:
  - `hard` is set on `ch>c` and not on `f>h`
  - a hard direction with 0 slips is not in `weakest_sounds`
  - a direction with 7 chances is absent
- `test_score_set_splits_weeks`: 30 tone rows at `days_ago=2` with score 1.0 and 30 at `days_ago=10` with score 0.5 give tones `{value: 0.75, last7: 1.0, prev7: 0.5, n: 60}`. The characters `last7` is None.
- `test_empty_rows`: every score on `[]` is `Score(None, 0)`, and every list function returns `[]`.
- `test_rank_sentences`: `{last: .80, best: .95}` is regressed and first; then non-regressed rows by `last` ascending.

- [ ] **Step 2: Run them to verify they fail.** Run `cd backend && PYTHONPATH=$PWD ~/shadow-speech/backend/.venv/bin/python -m pytest tests/test_stats_scores.py -q`. Expected: ImportError on `shadow.stats.scores` / `HARD_DIRECTIONS`.
- [ ] **Step 3: Add `HARD_DIRECTIONS` and implement `shadow/stats/scores.py`** with the signatures above. Use no DB or FastAPI imports in this module.
- [ ] **Step 4: Run the tests to verify they pass.** Run the same command; expect all pass. Then run the full backend suite to confirm nothing else broke.
- [ ] **Step 5: Commit** with message `feat(stats): pure score rules for characters, tones and hard sounds`.

---

### Task 2: Stats API under `/api/stats`, windowed details endpoints, Flow filter

**Files:**
- Modify: `backend/shadow/api/stats.py` (whole file except `lesson_stats`)
- Test: `backend/tests/test_stats_api.py`, `backend/tests/test_health.py`

**Interfaces:**
- Consumes: everything Task 1 produces.
- Produces these endpoints. `mode` is `Literal["flow"] | None = None` throughout, so any other value is a 422.
  - `GET /api/stats/activity?days=` has the same response as today. Its body is extracted to `_activity_days(db, days: int) -> list[dict]` for Task 3.
  - `GET /api/stats/characters?mode=` returns `{"characters": character_stats(rows)}`.
  - `GET /api/stats/tones?mode=` returns the response shape it has today. `tones` and `pairs` come from `tone_groups` over the 30-day rows. `weeks` covers 12 weeks with the same tone rule (missing counts 0, unvoiced left out).
  - `GET /api/stats/sounds?mode=` returns the shape it has today, and each sound row gains `hard: bool`. Rows come from `sound_directions` over the 30-day rows; `weeks` covers 12 weeks for the kept keys.
  - `GET /api/stats/sentences` returns `{"sentences": rank_sentences(...)}`. Each row is `{segment_id, lesson_id, lesson_title, idx, text, last, best, attempts, regressed}`:
    - `last` comes from the newest take in the window with a non-null `overall`
    - `best` is the best-ever `overall` of that segment (no window)
    - `attempts` counts the scored takes in the window
    - a segment with no scored take in the window is not listed
  - `/stats/syllables` is removed.
  - The helper `_rows(db, since: datetime, mode: str | None) -> list[SylRow]` joins `SyllableScore` to `Attempt`. It sets `created_at` to aware UTC, lower-cases `pinyin` and `heard`, and sets `tone` to `target_tone if not None else tone`. It is shared with Task 3.

- [ ] **Step 1: Update and write the failing tests.**
  - In `test_stats_shapes`, move every path to `/api/stats/...`. Assert:
    - `sentences` returns `{"sentences": []}`
    - `characters` returns `{"characters": []}`
    - `/api/stats/syllables` returns 404
  - Port `test_syllable_stats_per_character_with_trend` to `test_characters_endpoint`, against `/api/stats/characters` and the Task 1 fields.
  - Update `test_tone_stats_use_target_tones_and_weeks` and `test_stats_sounds_rates_by_direction` to the new paths.
  - Add `test_tones_window_and_missing_rule`. A row created 40 days ago is absent from `tones` and `pairs` but present in `weeks`. A `missing` row with NULL score lowers the mean as a 0.
  - Add `test_sounds_window_and_hard_flag`. Slips 40 days ago are absent from the rows. `ch>c` has `hard: true`.
  - Add `test_sentences_window_last_and_best_ever`:
    - Segment A has a take 60 days ago with `overall` 0.9 and one 2 days ago with 0.6. It gives `last 0.6, best 0.9, attempts 1, regressed True`, with `text`, `lesson_title` and `idx`.
    - Segment B's only take in the window has `score_json` None, so B is absent.
  - Add `test_mode_filter_flow_only`. With only echo takes, `?mode=flow` returns empty lists from characters, tones and sounds. `?mode=echo` returns 422.
  - Add to `test_health.py`:

```python
def test_spa_serves_stats_pages(data_dir, tmp_path, monkeypatch):
    dist = tmp_path / "dist"; dist.mkdir(); (dist / "index.html").write_text("<html>spa</html>")
    c = _spa_client(data_dir, dist, monkeypatch)
    for p in ("/stats", "/stats/characters", "/stats/tones", "/stats/sounds", "/stats/sentences", "/stats/activity", "/stats/drills"):
        assert c.get(p).text == "<html>spa</html>", p
    assert c.get("/api/stats/tones").json()["tones"] == []
```

  To create attempts at a given age, extend the existing helper as `_scores(client, rows, *, days_ago=0, mode="echo")`. Add `_take(client, seg_id, *, days_ago, overall, mode="echo")` for sentence takes. Pass `created_at` explicitly.
- [ ] **Step 2: Run them to verify they fail.** Run `... -m pytest tests/test_stats_api.py tests/test_health.py -q`. Expected: 404s on the `/api/stats` paths, and JSON instead of the SPA on `/stats/tones`.
- [ ] **Step 3: Implement.** Change the router to `APIRouter(prefix="/api/stats")` for the stats routes. `lesson_stats` keeps its `/lessons/{id}/stats` path; give it its own router or an explicit path. Then implement `_rows`, the endpoints above, and remove `syllables`.
- [ ] **Step 4: Run them to verify they pass,** then run the full backend suite.
- [ ] **Step 5: Commit** with message `feat(stats): /api/stats endpoints with a 30-day window, characters, sentence text and a Flow filter`.

---

### Task 3: `GET /api/stats/overview`

**Files:**
- Modify: `backend/shadow/api/stats.py`
- Test: `backend/tests/test_stats_api.py`

**Interfaces:**
- Consumes: `_rows`, `_activity_days` and the sentence builder from Task 2 (factor the sentence list into `_sentences(db, since) -> list[dict]` there, if Task 2 did not); `score_set`, `character_stats`, `weakest_tones` and `weakest_sounds` from Task 1; `recent_sessions(db, 2)` from `shadow.drill.summary`.
- Produces: `GET /api/stats/overview`, returning:

```
{"scores": score_set(all 30-day rows, now), "flow": score_set(flow 30-day rows, now),
 "weakest": {"characters": first 3 of character_stats(rows) with takes >= MIN_WEAK, sorted by (score, -takes, ch),
             "tones": weakest_tones(rows), "sounds": weakest_sounds(rows)},
 "activity": {"minutes": float, "takes": int, "days": int},   # last 7 days; days = days with ≥ 1 take
 "sentences": first 3 of _sentences(...), "drills": recent_sessions(db, 2)}
```

- [ ] **Step 1: Write the failing tests:**
  - `test_overview_scores_and_weekly_change`:
    - Write rows through the DB: 30 tone-3 syllables 2 days ago with score 1.0, and 30 syllables 10 days ago with score 0.5. These come back as naive datetimes.
    - Assert `scores.tones == {"value": 0.75, "last7": 1.0, "prev7": 0.5, "n": 60}` (approx).
    - Write 30 more syllables as `mode="flow"` 2 days ago with score 0.2. Assert `flow.tones.value == 0.2` and `flow.tones.prev7 is None`.
  - `test_overview_lists_and_activity`:
    - Four sentences with takes give exactly 3 entries in `sentences`, ranked as in Task 1, each with `text`.
    - Three ended drills with takes give 2 entries in `drills`.
    - `activity.takes` counts takes from the last 7 days only. A take 8 days ago does not count, and `days` is the number of distinct days.
    - A character with 7 takes never appears in `weakest.characters`.
  - `test_overview_empty`: an empty DB returns 200. Every score has `value` None and `n` 0, and every list is empty.
- [ ] **Step 2: Run them to verify they fail.** Expected: 404 on `/api/stats/overview`.
- [ ] **Step 3: Implement the endpoint.** Load the rows once for all takes and once with `mode="flow"`. Compute `now` once and pass it to `score_set`.
- [ ] **Step 4: Run them to verify they pass,** then run the full backend suite.
- [ ] **Step 5: Commit** with message `feat(stats): overview endpoint with scores, Flow scores, top-3 lists, activity, sentences and drills`.

---

### Task 4: Frontend types, client, display helpers and shared stats parts

**Files:**
- Modify: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`, `frontend/src/api/client.test.ts`
- Create:
  - `frontend/src/lib/statsView.ts` and `statsView.test.ts`
  - `frontend/src/components/stats/ScoreCard.tsx` and `ScoreCard.test.tsx`
  - `frontend/src/components/stats/Widget.tsx`
  - `frontend/src/components/stats/DetailsHeader.tsx`
- Move: `ActivityChart` out of `frontend/src/pages/Stats.tsx` into `frontend/src/components/ActivityChart.tsx`, unchanged.

**Interfaces:**
- Produces, in `types.ts`:
  - `Score { value: number | null; last7: number | null; prev7: number | null; n: number }`
  - `ScoreSet { characters: Score; tones: Score; sounds: Score }`
  - `CharStat { ch; pinyin; score; tone_right; sound_right: number | null; takes; trend: number | null }`
  - `ToneItem { kind: 'tone' | 'pair'; key; label; mean; n }`
  - `SentenceRow { segment_id; lesson_id; lesson_title; idx; text; last; best; attempts; regressed: boolean }`
  - `StatsOverview { scores: ScoreSet; flow: ScoreSet; weakest: { characters: CharStat[]; tones: ToneItem[]; sounds: SoundStats['sounds'] }; activity: { minutes: number; takes: number; days: number }; sentences: SentenceRow[]; drills: DrillRecent[] }`
  - `CharacterStats { characters: CharStat[] }`
  - Change `SentenceStats` to `{ sentences: SentenceRow[] }`, add `hard: boolean` to the `SoundStats` rows, and delete `SyllableStats`.
- Produces, in `client.ts`, `api.stats`:
  - `overview()`
  - `characters(mode?: 'flow')`
  - `tones(mode?: 'flow')`
  - `sounds(mode?: 'flow')`
  - `sentences()`
  - `activity(days = 30)`
  - `lesson(id)`, unchanged
  - All of them except `lesson` use the `/api/stats/...` paths; `?mode=flow` is appended only when given. `syllables` is removed.
- Produces, in `statsView.ts`:
  - `scoreText(v: number | null): string`: `'—'`, or `String(Math.round(v * 100))`
  - `changeText(s: Score): string`: `'—'` unless both `last7` and `prev7` are numbers; then `d = Math.round((last7 - prev7) * 100)`, giving `'▲ d'`, `'▼ |d|'` or `'±0'`
  - `HOW: Record<'characters' | 'tones' | 'sounds', string>`: the three card texts, verbatim
  - `UNIT = { characters: 'characters', tones: 'syllables', sounds: 'syllables' }`
- Produces these components:
  - `<ScoreCard title: string; score: Score; unit: string; how: string; to: string />`:
    - a notched card that is one `Link` to `to`, with a ring of `value` (track `line`, arc `accent`)
    - the number via `scoreText`, `changeText` labelled "vs last week", the text `` `${n} ${unit}` `` in small type, and `how`
  - `<Widget title: string; to: string; allLabel: string; empty: string; children />`: a notched card with the title, the children (or `empty` when there are none), and a `Link` "`allLabel` ›" to `to`.
  - `<Bar value: number />`: a small horizontal bar, exported from `Widget.tsx`.
  - `<DetailsHeader title: string; window?: string; flowOnly?: boolean />`:
    - a back `Link` "‹ Stats" to `/stats`, then the `h1` title
    - `window` defaults to `'Last 30 days'`
    - with `flowOnly`, a "Flow only" chip and a `Link` "All takes" to the current pathname without the query

- [ ] **Step 1: Write the failing tests:**
  - `statsView.test.ts`:
    - `scoreText(null) === '—'`, `scoreText(0) === '0'`, `scoreText(0.734) === '73'`
    - `changeText` with `prev7: null` gives `'—'`; with `last7: null` gives `'—'`
    - `.80/.75` gives `'▲ 5'`, `.70/.73` gives `'▼ 3'` and `.5/.5` gives `'±0'`
  - `client.test.ts`: `overview()` fetches `/api/stats/overview`, and `characters('flow')` fetches `/api/stats/characters?mode=flow`.
  - `ScoreCard.test.tsx`:
    - in a `MemoryRouter`, `{value: null, n: 12}` shows "—" and "12 syllables"
    - `{value: .62, last7: .7, prev7: .6, n: 312}` shows "62", "▲ 10" and the how text
    - the link has `href="/stats/tones"`
- [ ] **Step 2: Run them to verify they fail:** `cd frontend && npm test -- --run src/lib/statsView.test.ts src/components/stats src/api/client.test.ts`.
- [ ] **Step 3: Implement** the types, the client, `statsView.ts`, the three components and the moved `ActivityChart`. Keep `pages/Stats.tsx` compiling with the smallest possible edits: drop its Characters panel and render its Sentences panel from the new `sentences` list. Task 5 deletes the page.
- [ ] **Step 4: Run them to verify they pass,** then run the full frontend command (tests, eslint, tsc).
- [ ] **Step 5: Commit** with message `feat(stats): overview types and client, score card, widget and details header`.

---

### Task 5: The overview page

**Files:**
- Create: `frontend/src/pages/stats/Overview.tsx`, `frontend/src/pages/stats/Overview.test.tsx`
- Delete: `frontend/src/pages/Stats.tsx`. Its test moves to Task 6's pages; delete `Stats.test.tsx` here, along with the old tests Task 6 re-creates.
- Modify: `frontend/src/App.tsx` (`/stats` → `Overview`)

**Interfaces:**
- Consumes: `api.stats.overview()`, `ScoreCard`, `Widget`, `Bar`, `scoreText`, `changeText`, `HOW`, `UNIT`, and `pct` from `lib/score`.
- Layout, top to bottom, inside `Shell` with `max-w-4xl mx-auto p-6 space-y-4`:
  1. `h1` "Stats". The empty line "Practise a few sentences to see your scores." appears when all three `scores.*.n` are 0.
  2. Three `ScoreCard`s, linking to `/stats/characters`, `/stats/tones` and `/stats/sounds`.
  3. Three `Widget`s:
     - Characters: `ch` in `font-hanzi`, then pinyin, a `Bar` of `score` and `pct(score)`. Link "all characters" goes to `/stats/characters`.
     - Tones: `label`, a `Bar` of `mean` and `pct(mean)`. Link "all tones" goes to `/stats/tones`.
     - Sounds: `label`, then "`slips` of `chances`" and a `Bar` of `rate`. Link "all sounds" goes to `/stats/sounds`.
  4. The second row, in this order:
     - **Flow:** the three Flow scores, each with `scoreText` and `changeText`. Each links to its details page with `?mode=flow`.
     - **Activity:** "`round(minutes)` min · `takes` takes · `days` of 7 days". Link "activity" goes to `/stats/activity`.
     - **Sentences to revisit:** each entry is a button showing the `text` (one line, truncated), then `lesson_title` small below it and `pct(last)` at the right. A click navigates to `/practice/${lesson_id}?idx=${idx}`. Link "all sentences" goes to `/stats/sentences`.
     - **Drills:** "`label` `pct(first_mean)` → `pct(best_mean)`". Link "all drills" goes to `/stats/drills`.
  - Grid: one column on narrow screens; three columns for rows 2–3; two columns, then four on `lg`, for row 4.
  - While the overview loads, show "Loading…". If it fails, show "Could not load stats: …" in `text-bad`.

- [ ] **Step 1: Write the failing tests** in `Overview.test.tsx`. Mock `api.stats.overview` the way `Stats.test.tsx` mocks its client, with a fixture that has values in every part.
  - `shows the three scores with change and n`: "73", "▲ 4" and "312 syllables" are present.
  - `shows the weakest of each area`: 好, "1 → 0", "uo said as ou" and "22 of 45" are present.
  - `a sentence opens in Practice`: clicking its text routes to `/practice/7?idx=3`. Use the `Where` routing helper from the old `Stats.test.tsx`.
  - `the Flow widget links to the Flow-only details`: the Tones link has `href="/stats/tones?mode=flow"`.
  - `empty overview`: all `n` 0 and empty lists show "Practise a few sentences to see your scores." and "—" on the cards.
  - `load error`: a rejected promise shows "Could not load stats".
- [ ] **Step 2: Run it to verify it fails:** `npm test -- --run src/pages/stats/Overview.test.tsx`.
- [ ] **Step 3: Implement** `Overview.tsx`, route `/stats` to it, and delete `pages/Stats.tsx` and its test.
- [ ] **Step 4: Run it to verify it passes,** then run the full frontend command.
- [ ] **Step 5: Commit** with message `feat(stats): overview page with score cards, top-3 widgets, Flow, activity, sentences and drills`.

---

### Task 6: Details pages and routes

**Files:**
- Create: under `frontend/src/pages/stats/`, `Characters.tsx`, `Tones.tsx`, `Sounds.tsx`, `Sentences.tsx`, `Activity.tsx`, `Drills.tsx` and `Details.test.tsx`
- Modify:
  - `frontend/src/App.tsx`: add six routes, `/stats/characters` … `/stats/drills`
  - `frontend/src/components/SoundsPanel.tsx`: a "hard" marker on rows with `hard`
  - `frontend/src/components/SoundsPanel.test.tsx`: update the fixtures for `hard`

**Interfaces:**
- Consumes: `DetailsHeader`, `ActivityChart`, `ToneTrend`, `ToneMatrix`, `SoundsPanel`, `api.stats.*` and `api.drill.recent(10)`.
- Each page renders `Shell`, then `DetailsHeader`, then its content in a notched `Card`. Characters, Tones and Sounds read `mode` with `useSearchParams().get('mode') === 'flow'`, pass it to the client and set `flowOnly`.
  - **Characters:**
    - note under the header: "Characters you've said at least 3 times in the last 30 days. Neutral-tone characters are left out: their tone isn't scored."
    - one row per `CharStat`: `ch` (`font-hanzi`), then pinyin and `pct(score)`, then "tone `pct` · sound `pct` or —", then "`takes` takes"
    - the trend as `↑ n` / `↓ n` (as today), and **Drill this** with `aria-label` "Drill `ch`"
  - **Tones:** the current Tones panel content: `ToneTrend`, a row per tone with Drill this for tones 1–4, and `ToneMatrix` with `onDrill`.
  - **Sounds:** `SoundsPanel` with `onDrill`. The footer note is the verbatim copy, and a line says hard sounds are the ones the score uses.
  - **Sentences:** one button row per `SentenceRow`, showing `text`, then `lesson_title` (small), "last `pct`", "best `pct`" and "`attempts` takes". A "regressed" badge appears when `regressed` is true. A click opens `/practice/${lesson_id}?idx=${idx}`.
  - **Activity:** `DetailsHeader` with `window` "Last 30 days", and `ActivityChart` over `api.stats.activity(30)`.
  - **Drills:** `DetailsHeader` with `window` "Last 10 drills", and the recent-drills list as on the old page (`data-drill-label`, `first → best`, "No drills yet.").

- [ ] **Step 1: Write the failing tests** in `Details.test.tsx`, mocking `api.stats` and `api.drill`:
  - The four drill-navigation cases from the old `Stats.test.tsx`, unchanged: `Drill tone 3`, `Drill 好`, `Drill tone pair 3→3` and `Drill ch said as c`. Each is rendered on its own page.
  - `characters page lists rows with trend`: 好, "hǎo" and "↑ 20" are present. With `sound_right: null` it shows "sound —".
  - `flow-only header links back to all takes`:
    - render `/stats/characters?mode=flow`
    - expect `api.stats.characters` to have been called with `'flow'`
    - expect the text "Flow only" and a link "All takes" with `href="/stats/characters"`
  - `sounds page marks hard sounds and says what is not checked`: there is a "hard" marker on `ch said as c` and the footer text is present.
  - `sentences page shows text, regressed badge, and opens Practice`.
  - `drills page lists recent drills with first → best, or says there are none`: ported from the old test.
  - `back link returns to the overview`: the "‹ Stats" link has `href="/stats"`.
- [ ] **Step 2: Run it to verify it fails:** `npm test -- --run src/pages/stats/Details.test.tsx`.
- [ ] **Step 3: Implement** the six pages, the routes and the SoundsPanel marker.
- [ ] **Step 4: Run it to verify it passes,** then run the full frontend command and the full backend suite.
- [ ] **Step 5: Commit** with message `feat(stats): details pages for characters, tones, sounds, sentences, activity and drills`.
