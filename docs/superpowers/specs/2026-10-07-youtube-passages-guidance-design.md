# Phase 1.5 — YouTube lessons, passages, listening cards, practice guidance

Addendum to `2026-10-03-shadowing-tool-design.md` (the "main spec"). Where the
two disagree, this document wins for the topics it covers. Agreed with the user
on 2026-10-07.

## 0. Intent

**What the user said.** Mining sentence by sentence in Brave (asbplayer +
Yomitan → Anki) is no longer the input. He mostly watches YouTube. A lesson is
the whole video and every sentence in it is practice material. Speaking is
practised in the app; Anki is for **listening** review of sentences he has
already practised. The app must tell him what to do at every moment and give
karaoke-style cues in Flow; the reference volume must be adjustable and quieter
by default when speaking along. English subtitles are not used.

**Success.** Find a Chinese video on YouTube, send it to shadow-speech in one
step, and a few minutes later shadow it passage by passage, always knowing
when to listen and when to speak; at the end of a session the practised
sentences go to the `shadow-speech` Anki deck as listening cards in one click.

**Not in scope.** English subtitles; further work on Anki import (it stays as
built); showing the video in the app; vocabulary/word cards; Phase 2 scoring.

## 1. Prerequisite fixes (done first, independent of the rest)

### 1.1 Alignment repair against ASR character times

The Qwen3 forced aligner predicts boundaries on an 80 ms grid and often returns
a zero-length span (start = end) for a character, and sometimes starts a
sentence's first character up to ~1 s before the speech. In lesson 1, 25 of 52
sentences start with a zero-length character; Paraformer's own per-character
times for the same characters are consistent.

After alignment, each span is checked against the coarse time of the same
character (ASR char time; for subtitle-sourced text, the subalign time):

- a span shorter than 40 ms, or whose start differs from the coarse start by
  more than 0.3 s, is replaced by the coarse span;
- spans are then made monotonic (end ≥ start, start ≥ previous end);
- the replacement is recorded as `conf = 0.5` (aligner spans 1.0, uniform
  fallback 0.0), so the source of each timing stays visible.

Anki-sourced segments have no coarse char times; there, a zero-length span
takes the gap up to the next span's start (split evenly among consecutive
zero-length spans).

A one-off comparison runs the MMS_FA aligner on lesson 1 against the repaired
Qwen3 spans and the ASR times (measured as first-character onset error against
an energy onset and the share of zero-length spans). If MMS_FA is clearly
better, `aligner = "auto"` resolves to `mms_fa` on CUDA too; the result is
recorded in the plan's ledger either way. Existing lessons improve only when
re-ingested.

### 1.2 Syllable click plays once

Clicking a feedback cell plays that syllable's span once; clicking again plays
it again. (Main spec §7.2 "loops" is replaced.)

## 2. YouTube ingest (replaces main spec Phase 4 YouTube row)

- **API:** `POST /lessons/youtube {url}` → `{job_id, lesson_id}`. Accepts
  `youtube.com/watch?v=…`, `youtu.be/…`, `youtube.com/shorts/…`, with or without
  `&t=`. The video id is the lesson's `source_ref` (`youtube::<id>`); adding a
  video that already has a lesson returns that lesson (no new job) unless it is
  in `error`, in which case it is re-ingested.
- **Download:** `yt-dlp` as a Python dependency (pinned, `uv` managed), behind a
  `Downloader` protocol with a `FakeDownloader` for tests. Audio only
  (best audio stream), then the existing normalise step. Optional
  `[youtube] cookies_file`; `[youtube] enabled` defaults to **true** now.
- **Metadata:** lesson title = video title (t2s), speaker = channel name (t2s),
  `meta_json` keeps `url`, `channel`, `upload_date`, `duration`, `chapters`.
- **Chinese subtitles:** prefer manual `zh-Hans`, then `zh-Hant`/`zh-TW`/`zh`,
  then auto-generated `zh-Hans`/`zh`; fed to the existing subtitle path (text
  from subtitles, timing from ASR, rolling-cue dedupe, match guard). No Chinese
  subtitles → ASR text. English and other languages are never downloaded.
- **Progress stages:** `download` then the existing stages.
- **Errors (readable, lesson → `error`, deletable):** private/unavailable
  video; sign-in/age/bot check ("this video needs a cookies file — see
  Settings"); network failure; extraction failure that suggests an outdated
  yt-dlp ("update yt-dlp: `cd backend && uv lock --upgrade-package yt-dlp && uv
  sync --extra dev --extra models`"); video longer than `[youtube] max_minutes`
  (default 90).
- **Docs:** `docs/running.md` gains a YouTube section (cookies export, Deno if
  yt-dlp asks for it, updating yt-dlp).

## 3. Hand-off from Brave

- **Library:** a "Paste a YouTube link" field next to Upload; Enter submits.
- **Bookmarklet:** Settings shows a draggable "→ shadow-speech" link:
  `javascript:location.href='<app>/library?add='+encodeURIComponent(location.href)`
  where `<app>` is the app's current origin. Opening `/library?add=<url>` asks
  "Add <title or url> to shadow-speech?" and on yes submits it, then removes
  the parameter from the address bar.

## 4. Passages

A **passage** is a contiguous run of segments of about 2–3 minutes; it is the
unit of Flow runs and of progress. Applies to every lesson source.

- **Built** after `build_segments` (and rebuilt after resplit/merge), stored as
  rows `Passage(id, lesson_id, idx, title, start_s, end_s)`; a segment belongs
  to the passage whose time range contains its `start_s`, so edits never break
  the mapping.
- **Boundaries:** YouTube chapters when the video has them (chapter title =
  passage title; chapters longer than 4 min are split as below). Otherwise
  greedy: accumulate segments to a 150 s target and cut at the largest pause
  between consecutive segments within 120–180 s; the last passage absorbs a
  remainder under 60 s. Titles default to "Passage N · mm:ss–mm:ss". Lessons
  shorter than 4 min have one passage.
- **Done:** a passage is done when every segment in it has at least one
  attempt.
- **UI:** Practice shows a passage selector in the top bar ("Passage 4 / 9");
  Flow's range defaults to the current passage; the drawer groups segments
  under passage headers with a ✓ when done; the library tile shows
  "4 / 9 passages".
- **API:** `GET /lessons/{id}` includes `passages: [{idx, title, start_s,
  end_s, segment_ids, done}]`.

## 5. Anki: listening cards and session-end export

### 5.1 Note type and deck

Settings → Anki gains **"Set up shadow-speech deck"**, which after a
confirmation creates (via AnkiConnect `createDeck`, `createModel`) the deck
`shadow-speech` and the note type **"Shadow Listening"**, unless they exist,
and fills the export settings with them.

- **Fields:** `Audio`, `Sentence`, `Pinyin`, `Translation`, `Source`, `Link`.
- **Front:** `{{Audio}}` (Anki auto-plays it) and the prompt "What did you hear?"
- **Back:** `{{FrontSide}}`, rule, `{{Sentence}}`, `{{Pinyin}}`,
  `{{Translation}}`, and `{{Source}}` linked to `{{Link}}`.
- `Source` = "<lesson title> · mm:ss"; `Link` = the YouTube URL with
  `&t=<seconds>` (empty for non-YouTube lessons). Tags: `shadow`,
  `shadow::<lesson id>`.

The existing configurable export (any deck/note type with sentence, audio,
pinyin, translation mapping) remains; Source and Link are optional mapping
targets.

### 5.2 What gets exported, and when

- **Practised** = a segment with at least one attempt (any mode, Flow slices
  included).
- **Session-end dialog:** on "Finish session" (new transport button), on
  closing the Flow summary, and on in-app navigation away from the practice page
  (library link, lesson switch) with practised sentences not yet in Anki — not
  on closing the tab, which the Review list below covers — a dialog lists this session's practised
  sentences that have no `anki_note_id`. All are ticked except **fillers**:
  fewer than 4 speech characters, or made only of interjections
  (嗯 啊 哦 呃 对 好 是 嗯嗯 对对 好的 是的). One click sends the ticked ones;
  per-row result; sent rows record `anki_note_id`.
- **Nothing is lost when Anki is closed:** the Review page gains a
  "Practised, not in Anki" list (server-computed: segments with attempts and
  no `anki_note_id`, newest first) with the same bulk send.
- Manual A / "A → Anki all" stay as built.

## 6. Practice guidance

### 6.1 Mode tooltips
Hover text on each mode tab (also used by the help overlay):
- **Echo** — "One sentence at a time: listen, then repeat it on your own. You
  hear the original and your take back to back."
- **Chorus** — "Speak at the same time as the sentence, N times in a row. Only
  the last pass is recorded."
- **Flow** — "Shadow a whole passage without stopping. After: each sentence
  plays, then you repeat it in the pause. Along: speak at the same time as the
  audio (use headphones)."
- **Guided** — "Four steps per sentence: listen → whisper along with the text →
  say it with the text hidden → next."

### 6.2 Cue line
One line above the sentence, large, always stating the current instruction,
driven by a pure function `cueFor(mode, state) → {icon, text, tone}`:
🎧 **Listen** (reference blue) · 🗣 **Your turn — speak now** (your amber) ·
🎤 **Speak along** (amber) · ⏸ **Ready — Enter to start** (neutral) ·
✓ **Done — Enter for next** (green) · errors in red. It replaces the
record-button label as the primary cue (the button keeps a short label).

### 6.3 Microphone meter
While the mic is open, a small level meter next to the cue line (RMS from the
recorder, ~20 updates/s), so it is visible that speech is being picked up.

### 6.4 Help overlay
`?` opens an overlay with the four mode descriptions and the key map; it opens
once automatically on the first visit to a practice page (remembered in
localStorage), and closes with Esc or `?`.

### 6.5 Karaoke cues (all modes during reference playback; central in Flow)
- **Colour wipe:** the sentence fills with the reference colour character by
  character in sync with `ref_alignment_json` (clip-relative). Drawn as an
  absolutely positioned overlay layer computed from the rendered text's
  character rectangles (`Range.getClientRects` on the base text of each ruby),
  `pointer-events: none`, `aria-hidden`. **The sentence DOM is unchanged**
  (main spec §7.7: one `<p lang="zh">`, ruby per word, no per-character
  elements), so Yomitan keeps working.
- **Ghost wipe:** in Flow *after* (from the start of the turn) and in Echo (from the
  moment recording starts), a fainter amber wipe runs during the learner's turn at the reference's pace (scaled by
  the playback rate).
- **Count-in dots:** ● ● ● disappearing over 1.5 s before the learner must
  start: before the turn in *after*/Echo, before each new line in *along*.
  Omitted when the preceding gap is shorter than 0.5 s.
- **Next-line preview (Flow):** current sentence large, next sentence dimmed
  below it.
- **Turn bar (Flow after):** a thin bar under the sentence that shrinks over
  the speaking window.
- Pure helpers (`wipeProgress(spans, t)`, `countInWindow(...)`) carry the
  timing logic and are unit-tested; components stay thin.

## 7. Volume

- **Reference volume** slider in the transport (0–100 %, default 100 %,
  persisted in settings), applied to every reference playback.
- **Guide level** for speaking along — Flow *along* and Chorus — default 50 %
  of the reference volume, adjustable live from the same transport (a second
  slider shown only in those modes), persisted.
- Your own takes play at the reference volume.
- **Headphones hint:** starting *along* or Chorus shows "Use headphones — the
  mic would pick up the reference" once per session.

## 8. Data and API changes (summary)

- New table `Passage` (§4); `Lesson.meta_json` YouTube keys (§2).
- `POST /lessons/youtube`; `GET /lessons/{id}` gains `passages`;
  `GET /review/unexported` (practised, not in Anki).
- Settings (frontend): `referenceVolume`, `guideLevel`, `helpSeen`.
- Config: `[youtube] enabled = true`, `max_minutes = 90`, `cookies_file`.

## 9. Error handling

YouTube failures end in a readable lesson error the user can delete (§2).
Anki set-up: an existing deck/note type is reused, never modified; AnkiConnect
errors are shown verbatim after a short explanation. Export failures are per
row; unsent rows stay in "Practised, not in Anki". Wipe/cue rendering never
blocks playback: missing alignment → no wipe, cue line still shown.

## 10. Testing

Backend: `FakeDownloader` (metadata, audio, optional zh VTT) for ingest,
dedupe, subtitle selection, every error path; passage builder (chapters,
greedy cut, remainder, rebuild after resplit/merge, time-based membership);
alignment repair (zero-length, early start, monotonic, conf 0.5, Anki gap
fill); unexported-review query. Frontend: `cueFor` for every mode/state,
`wipeProgress`, `countInWindow`, filler detection, export dialog selection,
bookmarklet `?add=` flow, volume persistence and guide level applied in along/
Chorus, tooltip text present, help overlay first-visit. Manual (acceptance):
a real YouTube video with and without Chinese subtitles, a cookies-required
video, Yomitan over a wiping sentence, guide level audible in Flow along.

## 11. Build order

1. Prerequisite fixes (§1).
2. YouTube ingest + hand-off (§2, §3).
3. Passages (§4).
4. Guidance and volume (§6, §7).
5. Listening cards and session-end export (§5).
