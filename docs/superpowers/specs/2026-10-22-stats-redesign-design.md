# Stats redesign — overview widgets, three scores, details pages

Agreed with the user on 2026-10-22. It builds on the Phase 2 (tones), Phase 3a (sounds) and 3b (drills) data. The **look** (colours, type, components) comes from the separate app-wide style project, which the user asked for at the same time: dark-mode friendly, Chinese colours, intuitive in the Steve Jobs sense, including a rethought bottom control bar. That project is brainstormed next and **built before this one**, so these pages are styled once. This document fixes content, structure and behaviour only.

## 0. Intent

**What the user said.**
- Stats has become "too big of a page".
- He wants widgets showing the top 3 that he can click to see a details page.
- He wants more analysis than sentence scores, as an overall score.
- Sentences and Characters "look really bad"; Tones and Sounds look good.
- Characters, tones and sounds are the general trackers of his performance across videos; whole sentences are specific.
- At the top he wants a general calculated score (0–100) for each of characters, tones and sounds.
- The sound score should focus on the sounds known to be hard for learners of Chinese, not f/h.

**Why the current page looks bad.**
- Sentences shows internal ids (`#451 · last 70 · best 80`) instead of the sentence.
- Characters is a flat list of 50 rows that includes noise: characters seen once or twice, and neutral-tone characters scoring 0 (识 shi, 5 takes, "mean 0").

**Success.** Opening Stats answers at a glance "how am I doing in characters, tones and sounds, and is it improving?", plus "what are my three weakest of each?". One click shows the full picture of any area, and from there one click starts a drill or opens a sentence in Practice.

**Not in scope.**
- The visual style (separate project).
- New measurements: j/q/x and aspiration (b/p, d/t, …) are not detected yet. The Sounds details page says so.
- Goals, streaks, gamification.
- Exporting stats.

**Anti-goals.**
- Numbers that move on noise. Small samples must never become a "worst" or swing a score.
- A score whose meaning the user can't tell. Each score card says in one line how it is counted.

## 1. Overview page (`/stats`)

Top to bottom:

### 1.1 Three score cards

Characters, Tones and Sounds. Each card has:
- a 0–100 number, rounded
- a ring or bar showing it
- the change "vs last week": the same score over the last 7 days minus the 7 days before, shown ▲/▼ n, or "—" when either week has no data
- a one-line "how it's counted" text, the sentences in §2

Clicking a card opens that area's details page.

### 1.2 Three area widgets

One each for Characters, Tones and Sounds. Each shows the **3 weakest** items with a small bar, and a link "all … ›" to the details page.

- **Characters:** the 3 characters with the lowest character score (§2.1) among those with **≥ 8 takes** in the window.
- **Tones:** the 3 lowest of tones 1–4 and tone pairs together, by mean tone score. **One tone-mean rule everywhere** (*my call*): the §2.2 rule, with missing rows counting 0 and unvoiced rows left out, so the card, widget, rows and matrix agree. It replaces today's `_SCORED` mean, which skips missing rows; the drill focus ranking already uses this rule. A pair needs ≥ 8 rows, as drills do (`[drill] min_rows`). Pairs are labelled "1 → 0" etc.; neutral 0 can appear as the second tone of a pair, as in the existing matrix.
- **Sounds:** the 3 **hard** directions (§2.3) with the highest slip rate (existing `/stats/sounds` semantics: ≥ 8 chances, label "uo said as ou", "22 of 45").
  - A direction with 0 slips is never listed as weak.
  - *My call*: limiting the widget to hard directions keeps it in line with the score. The details page lists every direction, with the hard ones marked.

### 1.3 Second row

- **Activity:** minutes and takes in the last 7 days, and the number of days practised in the last 7 days.
- **Sentences to revisit:** the 3 sentences most worth redoing, shown as the **sentence text** (and lesson title on hover or in a second line) with the last score. Ranking:
  - regressed sentences first (best − last ≥ 0.15), largest drop first;
  - then the lowest last score;
  - among sentences practised in the window.

  Clicking one opens it in Practice (`/practice/{lesson}?idx=…`).
- **Drills:** the last 2 ended drills, "label first → best" (existing data).

### 1.4 Flow widget (the user's addition)

the user sees the other modes as practice, and Flow as his real shadowing. One widget shows the **same three scores** (Characters, Tones, Sounds; §2 rules, same window, same small-sample rules), computed from **Flow takes only** (`Attempt.mode == "flow"`), each with its change vs last week.

- Placement is my call: on the second row, before Activity.
- Clicking it opens the Characters/Tones/Sounds details pages filtered to Flow (`?mode=flow`).
- Every details page accepts that filter, and its header shows "Flow only" with a way back to all takes.

## 2. The three scores

**Which takes count.** the user decided: **every** take counts (Echo, Chorus, Guided, Flow and drill takes) for all scores, lists and thresholds on Stats. The one exception is the Flow widget (§1.4), which uses Flow takes only.

**Window.** All three scores are computed over the **last 30 days** of attempts (*my call*, matching the drill window). Each is also computed for the last 7 days and the 7 days before, for the change on the card. Both are rolling windows from now.

**Small samples** (*my call*, from the anti-goal):
- A score with fewer than 30 counted units in its window shows "—". Units are syllables for Tones and Sounds, and qualifying characters (≥ 3 takes) for Characters, of which there must be at least 10.
- The ▲/▼ change shows only when both 7-day windows reach 30 syllables; for Characters, 10 qualifying characters each. Otherwise it shows "—".
- Each card shows its n in small text, e.g. "312 syllables".

### 2.1 Characters

1. A take of a character counts as **right** when its tone is right **and** its sound is right:
   - tone right: `SyllableScore.status == "ok"`
   - sound right: `sound_status` is `ok` or NULL; NULL means not checkable, so only the tone decides
   - `missing` rows count as not right; `unvoiced` rows are left out
2. Only hanzi count, and only those whose tone (`coalesce(target_tone, tone)`) is 1–4. Neutral tone is left out.
3. Character score = right takes / takes, per character. Only characters with **≥ 3 takes** in the window count.
4. Overall Characters score = **mean over characters** (each character weighs the same, so 的 said 80 times doesn't outweigh 飞 said 5 times), × 100.

The card text reads: "Share of your takes where both tone and sound were right, averaged over the characters you've practised (≥ 3 times, last 30 days)."

### 2.2 Tones

Mean `tone_score` over scored syllables whose tone is 1–4, with `missing` = 0 and `unvoiced` left out; the same rule as the sentence score. × 100.

The card text reads: "Your average tone score over all scored syllables in the last 30 days (neutral tone left out)."

### 2.3 Sounds — the hard sounds

1. The **hard directions** are the contrasts learners of Chinese find hardest that the detector can check:
   - zh/z, ch/c, sh/s (both ways)
   - r/l (both ways)
   - ü/u (both ways)
   - -n/-ng (both ways)
   - the vowel pairs ou/uo, an/en, ang/eng (both ways)
   - **Left out:** f/h (a dialect issue, not a learner one), ai/ei, ao/ou.
   - Sources: teaching literature and a learner study.
2. A checked syllable (`sound_status` not NULL) **counts** when `checkable_directions_of(pinyin_toneless)` contains at least one hard direction.
   - It is right when `sound_status == "ok"`.
   - A slip counts as wrong if `direction(pinyin_toneless, heard_syllable)` is a hard direction.
   - A slip on a non-hard direction (e.g. fan heard as han) is left out of this score entirely. *My call.*
3. Sounds score = right / counted, × 100.

The card text reads: "Share of syllables said right among the hard sounds — zh/ch/sh vs z/c/s, r vs l, ü vs u, -n vs -ng and the vowel pairs ou/uo, an/en, ang/eng; last 30 days. f/h is left out."

Freeze the hard-direction list in code next to `contrasts.py`, as a named constant with this comment and its sources.

## 3. Details pages

Each page:
- has a back link to `/stats`
- uses the same window as the overview (last 30 days) unless stated otherwise
- states that window in its header

- **`/stats/characters`.** Every character with ≥ 3 takes in the window, worst first. Each row shows:
  - character and pinyin
  - character score
  - tone right % and sound right %
  - takes
  - a small trend: the last 10 takes vs the rest, when ≥ 15 takes (the existing rule)
  - **Drill this** (`char`)

  A note under the header explains the ≥ 3 and neutral-tone rules.
- **`/stats/tones`.** The current Tones section unchanged in content: weekly trend (12 weeks), a row per tone, the tone-pair matrix, Drill this. Rows and the matrix use the 30-day window; the trend keeps its 12 weeks.
- **`/stats/sounds`.** The current Sounds panel: a row per direction with slips/chances, rate, weekly sparkline and Drill this, in the 30-day window. Hard directions are marked; the score uses them. Footer note: "Not checked yet: j/q/x mix-ups and breathy vs plain consonants (b/p, d/t, g/k, j/q, zh/ch, z/c)."
- **`/stats/sentences`.** Every sentence practised in the window, as text with lesson title. "Last" is the newest scored take in the window, "best" is the best ever, and "regressed" means best ever − last ≥ 0.15 (*my call*: an old best still shows a drop). Each row shows last, best and attempts, with a "regressed" badge when best − last ≥ 0.15. Sorted as in §1.3. Clicking a row opens Practice at that sentence.
- **`/stats/activity`.** The current 30-day activity chart.
- **`/stats/drills`.** The current recent-drills list (last 10).

## 4. Data and API (builder's shape, these semantics)

- **`GET /stats/overview`** returns, in one call:
  - the three scores, each with value, last-7, previous-7 and n
  - the three top-3 lists
  - the activity summary
  - the top 3 sentences, with text, lesson id/title and idx
  - the last 2 drills
- **`GET /stats/characters`** returns the full character list of §3.
- `/stats/sentences` gains the text, lesson id/title and idx (no more bare ids). Its window becomes 30 days.
- `/stats/tones` and `/stats/sounds` gain the 30-day window for their rows; the weekly series stay as they are.
- The existing `/stats/syllables` is replaced by `/stats/characters`. Remove it once nothing calls it.
- Score functions are pure and unit-tested on hand-made rows. The rules in §2 are the test cases:
  - the neutral tone is left out
  - unvoiced rows are left out and missing rows count as 0 or not-right
  - NULL sound counts as right for characters
  - f/h slips are left out of Sounds
  - a character needs ≥ 3 takes
  - there are empty windows

## 5. Navigation

- The Stats tab opens the overview.
- Details pages are sub-routes. Their back link and the browser back button return to the overview.
- **Drill this** and "open in Practice" work exactly as today.

## 6. Left to the builder and to the style project

- **Visual design** (colours, type, cards, rings vs bars, spacing, phone width): the app-wide style project.
- **Component structure**, and whether the overview fetches one endpoint or several in parallel. One is preferred.
- **Empty states**, e.g. "Practise a few sentences to see your scores."
