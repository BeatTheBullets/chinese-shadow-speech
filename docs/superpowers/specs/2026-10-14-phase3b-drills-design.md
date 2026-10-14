# Phase 3b — Drills

Addendum to `2026-10-03-shadowing-tool-design.md` (main spec) and
`2026-10-09-phase2-tone-scoring-design.md` (Phase 2). Agreed with the user on
2026-10-14. Phase 3 is split: **3a** (segmental detection) waits for the user's
check-set recording (`data/reports/phase3-checkset.md`); **3b** (this spec)
builds drills on what Phase 2 already measures and leaves a slot for weak
sounds from 3a.

## 0. Intent

**What the user chose.** Phase 3 should give both "which sounds were wrong" and
targeted drills, detection first; while 3a waits for data, drills come first.
A drill item is a **whole sentence**. The app picks the focus automatically
and Stats offers **Drill this**. A session is a **queue with retry until the
target syllables are green**. Drills live on a **separate Drill page** so the
queue can draw from **all lessons**.

**Success.** Open Drill, get 10–15 minutes of practice on the current weakest
spot (a tone, a tone pair such as 3→3, or a character), see the target
syllables turn green within a session, and see the same focus improve across
sessions.

**Not in scope.** Word snippets; spaced-repetition scheduling; streaks or
goals; Anki export from the Drill page; weak *sounds* as a focus (added when 3a
exists — the focus model below has a slot for it).

## 1. Focus

A **focus** is one of:

| kind | key | label | target syllable |
|---|---|---|---|
| `tone` | `"3"` | "tone 3 (low)" | target tone = 3 |
| `pair` | `"3-3"` | "tone pair 3→3" | previous target tone 3 and target tone 3 |
| `char` | `"在"` | "在 zài" | the character |

(`sound`, e.g. `"zh"`, is reserved for 3a.)

**Weakness** of a focus = the mean `tone_score` of your `SyllableScore` rows
that match it (tone and pair use the stored target tone, falling back to the
canonical tone; `prev_tone` for pairs; `ch` for characters) from attempts in
the last `window_days` (30), excluding `unvoiced` rows; rows with
`status = missing` count as 0 (as in Phase 2's sentence score). A focus
qualifies with at least `min_rows` (8) rows. Neutral tone 0 and non-hanzi are
not focuses. Characters qualify only with at least 8 rows from at least 2
different sentences.

`GET /drill/focuses` → `{"focuses": [{kind, key, label, mean, n}], "auto": {kind, key} | null}`
sorted weakest first (ties → larger n). `auto` is the first one, except that
if the most recent ended drill session had the same focus and the next
candidate's mean is within 0.05, `auto` is the next candidate (rotation, so the
same focus is not forced every time). The Drill page shows `auto` plus the
next two as alternatives.

## 2. Queue

`POST /drill/sessions {kind, key}` builds the queue and returns
`{id, kind, key, label, items: [{segment: SegmentOut, lesson_id, lesson_title,
targets: [syllable index…]}]}`.

Candidate sentences: segments of lessons with `status = ready`, with
`words_json` and a clip, 4–15 speech syllables, containing at least one target
syllable. Target syllables for a candidate are found from its `words_json`
syllables: tone/pair by canonical tone (pair: previous syllable's canonical
tone too), char by `ch`. (Canonical tones are good enough for picking; the
score uses the realised target tone.)

Ranking (`queue_size` = 10):
1. Drop sentences that were green on all their targets in either of your last
   two drill sessions of the same focus (a sentence "went green" when a drill
   attempt on it had every target syllable `ok`).
2. Score each remaining sentence: `2 × (number of target syllables, max 3)`
   `+ 2 × (1 − last overall score)` if practised, `+ 1` if never practised.
   Ties broken by segment id (stable).
3. Take the best, with at most `max_per_lesson` (4) from one lesson while other
   lessons still have candidates; order the queue by lesson then sentence
   order so similar audio follows.

`POST /drill/sessions` may instead carry `segment_ids` ("Drill again"): the
queue is then exactly those segments (that still exist), in that order, with
their targets recomputed.

Fewer than `queue_size` candidates → the queue is shorter; the response
carries `short: true`. No candidates → 404 "no sentences contain this focus".
A focus that does not qualify (§1) can still be drilled when chosen
explicitly (from Stats); the auto pick only uses qualifying focuses.

## 3. Data

- New table `DrillSession(id, kind, key, label, started_at, ended_at,
  items_json)`; `items_json` = the queue (segment ids and targets) as built.
- `Attempt` gains nullable `drill_session_id` (FK). Drill takes are posted to
  the existing `POST /segments/{id}/attempts` with `mode = "drill"` and form
  field `drill_session_id`; they are normal attempts (Phase 2 scoring, stats,
  stored takes all apply). `"drill"` joins the backend `MODES`.
- `PATCH /drill/sessions/{id} {ended: true}` ends a session.
- `GET /drill/sessions/{id}/summary` →
  `{id, kind, key, label, items: [{segment_id, lesson_id, lesson_title, text,
  targets, tries, first: {mean, green}, best: {mean, green, attempt_id},
  went_green}], first_mean, best_mean, green_first, green_best, n_targets,
  history: [{session_id, started_at, first_mean, best_mean}]}` — per item the
  first and best (highest target mean) drill take of this session; target
  mean = mean tone_score of the target syllables (missing = 0, unvoiced
  ignored); `green` = number of target syllables `ok`; `history` = the last 10
  ended sessions with the same focus, oldest first.
- `GET /drill/sessions?limit=10` → recent sessions with focus, dates,
  first_mean, best_mean (for Stats).
- Lesson delete removes its drill attempts as before (they are attempts);
  `DrillSession.items_json` may then reference missing segments — readers skip
  them.

## 4. Drill page (`/drill`)

- **Navigation**: "Drill" tab after Review in the top bar. Stats gets a
  "Drill this" button on every tone row, every tone-pair matrix cell with data,
  and every character row → `/drill?kind=…&key=…` starts that focus directly.
- **Start screen**: today's focus (auto) with its mean and n, two alternatives,
  each with **Start**; the last ended drill's summary link; empty state when no
  focus qualifies: "Practise a few sentences first — drills start once there's
  enough to know your weak spots."
- **Per sentence** (a pure step machine in `frontend/src/lib/drill.ts`):
  1. `listen-along` — the clip plays once at the guide level with the karaoke
     wipe; the mic is not recorded; Enter skips ahead to recording.
  2. `record` — an Echo take: Enter starts, Enter stops (takes shorter than
     `MIN_TAKE_S` are dropped as in Practice); the reference then your take
     play back (as in Echo).
  3. `review` — the feedback block (TwoTrack with score, cells, pitch lines,
     header) with the **target syllables outlined**; if every target syllable
     is `ok` → `next`; else if scored tries < `max_tries` (3) → `retry`
     (back to `record`); else `next`. A take whose score has `overall: null`
     (gate warning) shows the warning and does not count as a try. "→" skips
     to the next sentence at any time; "R" replays your last take.
- **Top bar**: focus label, "Sentence n / N", "Try t / 3".
- **Hint line**: gate warnings / words notice exactly as in Practice
  (`warningText` / `noticeText`).
- **Reused**: TwoTrack, KaraokeSentence, CueLine, VolumeSliders, ClipPlayer,
  useMic, toWav16k, peaks, api.segments.postAttempt. The text is hidden while
  recording when the existing setting says so.
- **End**: after the last item, or "Finish" → `PATCH ended` → summary view.
  Leaving the page mid-drill ends the session (best effort, like Practice
  sessions); its summary appears as "last drill" on the start screen.
- **Summary view**: first→best target mean and green counts; per focus history
  line (first and best per session); sentences that never went green with
  "Drill again" (a new session on just those — `POST /drill/sessions` with
  `segment_ids`) and "Open in Practice" (`/practice/{lesson}?idx=…` — if the
  Practice page does not support `idx` yet, add it: open at that sentence).

## 5. Stats

A **Drills** panel: the last 10 sessions — focus label, date, first→best mean.
Drill takes already count in tone means, the matrix and characters.

## 6. Config

`[drill]` in `config.toml`: `window_days = 30`, `min_rows = 8`,
`queue_size = 10`, `max_tries = 3`, `max_per_lesson = 4`, `min_syllables = 4`,
`max_syllables = 15`, `rotate_within = 0.05`.

## 7. Errors

- A sentence whose lesson is rebuilding (409 on upload) shows the message and
  can be skipped; a deleted segment in a queue is skipped.
- Network/upload failure: message in the hint line, the take stays playable,
  it does not count as a try.
- `POST /drill/sessions` for a focus with no candidates → 404 with a readable
  message on the start screen.

## 8. Testing

Backend: focus means and qualification (window, min rows, missing = 0,
unvoiced ignored, char needs 2 sentences), auto + rotation, queue rules
(contains focus, syllable range, skip recent green, per-lesson cap, ordering,
short queue, no candidates), sessions create/end/summary/list, attempt with
`mode=drill` + `drill_session_id`. Frontend: `lib/drill.ts` transitions
(listen → record → review → retry/next, try cap, gate warning not counted,
skip), the page (start, targets outlined, retry and next, summary, Drill
again), Stats "Drill this", empty states.
