# Mandarin Shadowing Tool — Design Spec v2

Date: 2026-10-03. Supersedes `shadowing-tool-spec.md` (kept for reference).
Incorporates the decisions recorded in `spec-review.md` and the Anki /
asbplayer / Yomitan integration discussion.

Build brief for Claude Code. Self-hosted, single-user, web-based Mandarin
shadowing tool: sentence-level practice loop with native reference clips, your
recording played back against the reference, tone-contour overlay, and a
pronunciation score. Lessons come from uploaded or downloaded video/audio, or
from sentences already mined into Anki with asbplayer.

Priorities, in order: (1) a practice loop pleasant enough for 20 minutes a day,
(2) clean sentence segmentation, (3) tone feedback, (4) segmental feedback.

---

## 1. Architecture

```
┌────────────────────────────┐  HTTP/SSE   ┌─────────────────────────────────┐
│ Frontend (SPA, in Brave on │ ──────────▶ │ FastAPI backend (Python, WSL2)  │
│ Windows)                   │             │  ingest jobs                    │
│ React + Vite + TS          │ ◀────────── │  ASR, rectify, align, enrich    │
│ AudioWorklet recorder      │  JSON/audio │  scoring service                │
│ <audio> playback           │             │  SQLite + files on disk         │
│ AnkiConnect client ────────┼─▶ Anki on Windows, 127.0.0.1:8765            │
└────────────────────────────┘             └─────────────────────────────────┘
                                              │ FunASR Paraformer-zh (ASR, char timestamps, punctuation)
                                              │ Qwen3-ForcedAligner-0.6B (GPU) / torchaudio MMS_FA (CPU)
                                              │ wav2vec2 Chinese CTC (GOP, Phase 3)
                                              │ parselmouth (F0)
                                              │ ffmpeg, yt-dlp (optional), jieba, pypinyin, opencc
                                              │ Anthropic API (rectification, translation)
```

The browser talks to AnkiConnect directly because both Brave and Anki run on
Windows; the WSL backend never has to reach the Windows host in Phase 1.

### 1.1 Repo layout

```
shadow/
  backend/                 Python 3.12, FastAPI, uv
    shadow/
      api/                 routers
      ingest/              sources (upload, youtube, anki), asr, rectify, align, enrich
      scoring/             aligner interface, tone, gop, prosody
      store/               SQLModel models, file layout
      schemas.py           pydantic API types (single source of truth)
      config.py            config.toml loader
    tests/
    fixtures/              committed TTS WAVs + TextGrids + cached LLM responses
  frontend/                React + Vite + TypeScript, Tailwind
  data/                    runtime (gitignored): lessons/, attempts/, models/
  config.toml
  docker-compose.yml       optional
  Makefile                 make dev / make test / make fixtures
```

### 1.2 Compute

GPU first, CPU degraded. `device = "auto"` picks CUDA when available (RTX 3070,
8 GB). Every model must also run on CPU, with these substitutions when no GPU
is present: aligner `mms_fa` instead of `qwen3_fa`; GOP model loaded lazily.

| Target | GPU | CPU (degraded) |
|---|---|---|
| Ingest 10-minute video | < 2 min | < 10 min |
| Score one attempt | < 1 s | < 3 s |
| Idle RAM (models loaded) | — | < 4 GB |

Models load lazily on first use and are kept resident. WSL currently exposes
7.7 GB RAM; raise it in `.wslconfig` if the CPU path is used.

### 1.3 Hosting

Backend binds `127.0.0.1:8000` by default (`[server] host`). Vite dev server on
`5173`. Production: FastAPI serves the built SPA. No auth; exposing it beyond
localhost means putting it behind Tailscale or similar.

---

## 2. Lesson sources

| Source | How | Phase |
|---|---|---|
| Upload | Audio or video file, optional subtitle file (SRT/VTT/plain text) | 1 |
| Anki import | Notes mined with asbplayer (or any note with sentence + audio) | 1 |
| YouTube URL | yt-dlp with user-supplied cookies file and Deno; `--write-subs` for `zh.*`; disabled unless configured | 4 |
| asbplayer live | Backend poses as AnkiConnect on 8766; mined lines appear as segments | 4 |

Every lesson has a `speaker` (channel name, uploader, or free text) so the
library can group by speaker.

---

## 3. Ingestion pipeline

### 3.1 Normalise

`ffmpeg` → 16 kHz mono WAV `source.wav`. Metadata: title, speaker, duration,
source type, original filename or URL.

### 3.2 Text

Text and timing are produced independently. Text, in order of preference:

1. **Subtitle file** (uploaded, or YouTube `zh` subs). Cues give text and coarse
   timing.
2. **ASR**: FunASR Paraformer-zh, default model
   `iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch`
   with `fsmn-vad` and `ct-punc`. Output: punctuated text, per-character
   timestamps, VAD segment boundaries. ASR sits behind an interface
   (`transcribe(wav) -> Transcript`) so another engine can be plugged in.

Everything is passed through `opencc` (t2s). The result is the lesson's
**raw transcript**: a list of characters, each with a coarse `start`/`end`
(from ASR timestamps, or interpolated inside the cue for subtitles), plus the
list of coarse segment boundaries (VAD segments or cues).

### 3.3 Rectify and segment (LLM)

Purpose: fix ASR errors and choose shadowable sentence boundaries without
detaching timing. Boundaries are expressed as **character index ranges** into
the raw transcript.

```
INPUT per chunk (≤ 600 raw characters, cut at coarse segment boundaries,
~60 characters of preceding context marked as context-only):
  { "chars": [ {"i": 0, "c": "我"}, {"i": 1, "c": "今"}, ... ] }

OUTPUT (structured output, schema enforced by the API):
  { "sentences": [ {"from": 0, "to": 11, "text": "我今天想跟你们聊一聊学中文的方法。"}, ... ] }
```

Instructions to the model:
- Group characters into natural, shadowable sentences or clauses of about
  6–25 characters. Split long sentences at commas, 的时候, 但是, 所以 and
  similar.
- `text` is the corrected, punctuated text for exactly characters
  `from..to` inclusive. Fix homophone errors, punctuation and clearly wrong
  fillers. Do not paraphrase, add or drop content.
- Ranges are contiguous, non-overlapping and cover every character.

Validation in code; on failure the chunk falls back to coarse segments split
at 。！？； and clause punctuation ，、： (so pieces stay near the 6–25 character
target):
- coverage and contiguity;
- `edit_distance(strip_punct(text), raw[from..to]) / len(raw[from..to]) < 0.25`;
- 2 ≤ len(text) ≤ 60.

Model: Anthropic Messages API, `ANTHROPIC_API_KEY`, default
`claude-sonnet-5-5`, effort `low`, structured outputs
(`output_config.format`), no `temperature` (Sonnet 5.5 rejects non-default
sampling). Responses cached by hash of chunk characters, so reruns cost
nothing.

Anki-sourced lessons skip this step: the note text is already clean.

### 3.4 Align

For each sentence, force-align the corrected text to `source.wav` inside the
window `[coarse_start - 1 s, coarse_end + 1 s]`. The aligner returns one span
per character (= syllable). Sentence timing: `start = first_span.start - 120
ms`, `end = last_span.end + 120 ms`, clamped to neighbours. The per-syllable
spans are stored as the segment's **reference alignment** and reused by the
scorer.

Aligner interface: `align(wav, text) -> list[Span(ch, start, end, conf)]`.
Implementations:
- `qwen3_fa` (default on GPU): `Qwen/Qwen3-ForcedAligner-0.6B` via
  `qwen-asr`. Raw hanzi in, character times out.
- `mms_fa` (CPU default): `torchaudio.pipelines.MMS_FA`, text romanised with
  `pypinyin` `Style.NORMAL`, one token per character. torchaudio ≥ 2.10,
  audio I/O via `soundfile`.
- `mfa` (optional, Phase 4): Montreal Forced Aligner Mandarin models.

Known limitation: erhua (花儿) is two characters but one syllable; v1 treats
儿 as its own short syllable and the tone scorer will usually mark it
`unvoiced`.

### 3.5 Enrich

- **Words and pinyin**: `jieba` segments the sentence into words;
  `pypinyin` per word with `Style.TONE`, `tone_sandhi=True`,
  `neutral_tone_with_five=True`, plus `Style.TONE3` for tone numbers. Stored
  per word with its character range (needed for ruby rendering). Display and
  canonical-tone labels only; the tone scorer compares against the reference
  recording.
- **Translation**: batched LLM call (20 sentences per request), English,
  optional, cached.
- **Clips**: `ffmpeg` cut of the padded sentence → `clips/{idx}.wav` (16 kHz)
  and `clips/{idx}.opus`; `.mp3` rendered on demand for Anki export.

### 3.6 Jobs

`POST /lessons` returns `{job_id}`; progress over SSE at `GET /jobs/{id}/events`
with stages `normalise`, `transcribe`, `rectify`, `align`, `enrich`,
`done | error`, each with a 0–1 fraction. Background worker: `asyncio` queue
plus a thread pool. One ingest job at a time; scoring requests are never
queued behind ingest.

---

## 4. Data model (SQLModel, SQLite; audio on disk)

```python
class Lesson:
    id, title, speaker, source_type  # upload | youtube | anki
    source_ref                        # filename, URL, or Anki query name
    duration_s, created_at, status, meta_json
    transcript_json                   # raw chars with coarse times (None for anki)

class Segment:
    id, lesson_id, idx, start_s, end_s
    char_from, char_to                # into transcript_json (None for anki)
    text, translation
    words_json                        # [{word, pinyin, tones, char_from, char_to}]
    ref_alignment_json                # [{ch, start, end, conf}]
    difficulty_flag, anki_note_id
    clip_wav_path, clip_opus_path

class Attempt:
    id, segment_id, session_id, created_at
    mode                              # echo | chorus | flow
    audio_path, duration_s, score_json

class Session:
    id, lesson_id, mode, started_at, ended_at, attempts_count

class SyllableScore:                  # one row per syllable per scored attempt
    id, attempt_id, segment_id, idx
    ch, pinyin_toneless, tone        # canonical tone 0–4 from words_json
    prev_tone                         # tone of the preceding syllable, for tone-pair stats
    tone_score, seg_score, status     # ok | suspect | missing | unvoiced
```

Every attempt is kept, and every scored attempt also writes its per-syllable
rows, so history can be queried at three grains without parsing JSON:

- **sentence**: last, best and trend per segment (from `Attempt`);
- **character / syllable**: a character's or toneless syllable's scores across
  every sentence it appears in (from `SyllableScore`);
- **tone**: mean per canonical tone over time, and per tone pair
  (`prev_tone`, `tone`) such as the third-tone sandhi sequences.

Scores are never written back to Anki. Editing a segment's text invalidates
its alignment, words, clips and cached scores, and re-runs §3.4–3.5 for that
segment.

---

## 5. Scoring service

Input: expected text, reference clip with its cached alignment, learner WAV.
Output JSON:

```json
{
  "overall": 0.82, "tone_overall": 0.78, "segmental_overall": null,
  "rate_ratio": 1.18,
  "ref_contour": {"f0_st": [...], "step_ms": 10, "boundaries": [0, 23, 41]},
  "usr_contour": {"f0_st": [...], "step_ms": 10, "boundaries": [0, 27, 49]},
  "syllables": [
    {"ch": "我", "pinyin": "wǒ", "tone": 3,
     "status": "ok | suspect | missing | unvoiced",
     "tone_score": 0.91, "seg_score": null,
     "ref_f0": [20 floats], "usr_f0": [20 floats],
     "ref_dur": 0.21, "usr_dur": 0.29}
  ],
  "pitch_range_st": {"ref": 9.5, "usr": 4.1},
  "warnings": ["low_voicing_ratio"]
}
```

`segmental_overall` and `seg_score` are `null` until Phase 3.

### 5.1 Learner alignment and quality gate

Align the expected text to the learner WAV with the same aligner. If the
learner recording is shorter than 40 % of the reference, or mean alignment
confidence is below the configured floor, return every syllable as `missing`
with a warning instead of per-syllable nonsense.

### 5.2 Tone score (Phase 2)

1. F0 for the whole clip with `parselmouth` (autocorrelation, 10 ms step,
   floor 60 Hz, ceiling 500 Hz; retry with a wider range if voicing ratio
   < 50 %).
2. Convert to semitones relative to the speaker's median F0 over the sentence;
   optionally divide by the speaker's interquartile range (`normalise_span`)
   so range differences do not count.
3. Per syllable, slice with the alignment, trim the first and last 15 %,
   interpolate voiced frames to 20 points. Fewer than 4 voiced frames →
   `unvoiced`, skipped and reported (normal for neutral tones, short
   syllables, creaky low third tones).
4. `tone_score = 1 - clamp(DTW(ref, usr) / norm, 0, 1)` with a Sakoe–Chiba
   band of 4, plus a slope-sign agreement term weighted for tones 2 and 4.
   Weights in config; calibrated against your own recordings (Phase 2
   notebook).
5. Return the full-sentence contours with syllable boundary indices for the
   overlay, and the sentence pitch ranges.

### 5.3 Segmental score (Phase 3): GOP, not ASR diff

Run the Chinese CTC model (default `wbbbbb/wav2vec2-large-chinese-zh-cn`,
config `gop_model`) on the learner WAV to get frame posteriors. For each
aligned syllable span, `gop = mean log P(expected char) - mean log P(best
competing char)`. Run the same on the reference clip once (cached) to get a
per-syllable baseline. Status: `suspect` when the learner's GOP falls more than
`gop_margin` below the baseline, `missing` when the aligned span collapsed or
confidence is low, otherwise `ok`. Added syllables show up as `rate_ratio` and
alignment warnings, not as per-character labels.

### 5.4 Prosody

`rate_ratio = usr_duration / ref_duration`. Per-syllable duration ratios
highlight syllables held > 1.8× or < 0.5× the reference.

---

## 6. Practice modes

All modes operate on one lesson and share the recorder, player and scorer.

| Mode | What happens | Why |
|---|---|---|
| **Echo** | Play one sentence → record → auto-play reference then your attempt → score | Trancy loop; fixing a specific sentence |
| **Chorus** | Loop one sentence N times (default 5) with a 300 ms gap; speak along; the last pass is recorded and scored. Headphones required | Kjellin / Refold drill; strongest for tone and rhythm |
| **Flow** | Play a range of sentences continuously while recording continuously. Sub-mode `after` leaves a gap of `gap_factor × duration` (default 1.1) after each sentence; sub-mode `along` plays back to back and you speak over the audio. The browser slices the recording per sentence from the playback schedule and submits each slice as an attempt | Continuous shadowing as the interpreter tradition and Argüelles practise it; yields a worst-sentences list to drill in Echo or Chorus |
| **Guided** | Per sentence: listen once → one chorus pass with text visible, not scored → one echo pass with text hidden, scored | The article's progression |

Behaviour common to all modes:
- Text visibility toggles (hanzi, pinyin, translation) are remembered per
  lesson. Default: hanzi and pinyin on, translation off. Text auto-hides
  while recording (`hide_text_while_recording`, default on).
- A "move on" hint after 4 attempts on the same sentence; auto-advance on
  score is off by default.
- Session timer turns amber at 20 minutes.
- Playback speed 0.6–1.0 with a one-tap 0.75. Implemented with `<audio>`
  elements and `preservesPitch`; no server-side time stretching.

### 6.1 Recording

The browser captures PCM with an `AudioWorklet`, downsamples to 16 kHz mono,
and submits 16-bit WAV. This avoids `MediaRecorder` container differences
(iOS records mp4), gives a browser-side RMS VAD for free (stop after 1.2 s of
silence following speech in Echo), and lets Flow mode slice precisely using
`AudioContext.currentTime` stamps taken at each clip start. Slices get 150 ms
of slack on each side, trimmed by VAD on the backend.

---

## 7. Frontend

Decided in the UI brainstorm of 2026-10-03 (mockups under
`.superpowers/brainstorm/`). Desktop first; a phone layout is not a v1 goal.

Pages: **Library**, **Practice** (one lesson), **Review** (segments flagged or
with last score below threshold, oldest first), **Stats**, **Settings**
(AnkiConnect URL, import queries and field mapping, models, scoring weights,
practice defaults).

### 7.1 Practice page: stage + drawer

Two columns. Left, about two thirds, is the **stage**; right is the **lesson
drawer**, open by default and collapsible to a thin strip with a keyboard
toggle (L).

- **Top bar**: lesson title and speaker, progress `12 / 48`, mode switch
  (Echo · Chorus · Flow · Guided), session timer that turns amber at 20 min.
- **Stage, sentence block**: the current sentence rendered as in §7.7, with
  pinyin and translation lines below it, each toggleable. Font size steps with
  length: about 40 px up to 10 characters, 32 px to 18, 28 px to 25, 24 px
  beyond, wrapping at punctuation.
- **Stage, feedback block** (§7.2).
- **Stage, transport bar**: ◀ prev · ▶ play (Space) · ● record (Enter) ·
  chorus (C) · speed 0.6–1.0 with one-tap 0.75 · repeat count · next ▶ (→) ·
  flag ⚑ (F) · text toggles (T hanzi, P pinyin, E translation) · send to Anki
  (A) · edit / resplit / merge-next (in a small menu).
- **Drawer**: every sentence of the lesson, one line each with ellipsis and
  full text on hover, a score dot (grey none, green / orange / red by last
  score, dashed while scoring is pending) and a flag mark. Click to jump.
  Hover shows last and best score and a sparkline of all attempts.

### 7.2 Feedback block: two tracks with character cells

Reference track above, your track below, both on **one shared time scale** so
a slower attempt is visibly longer; the longer track fills the width.

Each track has: a header line, a waveform with a moving playhead and thin
tick marks at the syllable boundaries from the alignment, and a **row of
equal-width character cells** under it (max width capped and centred for short
sentences; wraps beyond about 28 cells). Click a cell on either track to loop
that syllable's span; hover a cell to see its pinyin.

- **Reference track**: header `Reference · 2.4 s · ▶`; cells show character,
  pinyin and canonical tone number.
- **Your track**: header `You · 2.8 s · 1.18×` plus the **visible score**:
  overall as a large number, chips for tone, segmental, best so far and attempt
  count. Cells show character, tone number and tone score; cell colour is the
  tone score (green ok, orange low, grey `∅` unvoiced, red missing). A thin
  orange bottom border marks a segmental `suspect` (Phase 3). The reference
  pitch line is drawn faintly behind yours, so the overlay comparison is kept.

Phase 1 state: both tracks show waveforms, playheads and cells with tone
numbers; score chips read "score arrives in Phase 2"; cells are neutral with a
dash where the score will go. Phase 2 adds pitch lines, cell colours and tone
scores; Phase 3 adds segmental chips and suspect borders. The block never
changes shape between phases.

### 7.3 Flow mode: the drawer becomes the stage

While Flow runs, the drawer expands to full width and scrolls like a
transcript. Passed lines dim and receive their score dot as the backend
catches up; the current line grows in place with its pinyin and a live
microphone strip with a "your turn" cue (in `after` sub-mode); the next lines
stay readable but smaller. Transport reduces to ⏸ · ■ stop · skip · speed ·
after/along. On stop, the layout returns to stage + drawer and shows the
**Flow summary**: mean score with tone and segmental means, rate, sentences
done and skipped; the weakest sentences with one-click `Echo` and `Chorus ×5`
buttons; replay the whole run (reference and you interleaved); run again; flag
or send-to-Anki the weakest three. In Phase 1 the summary lists sentences with
per-line replay and no scores.

### 7.4 Library: tiles grouped by speaker

Top: a drop zone for audio/video (+ `.srt`) that also accepts a pasted
YouTube URL, with `Upload` and `Anki import` buttons. Below, one section per
speaker, the **language parent** (a starred speaker) pinned first, each with
lesson tiles: title, sentence count, practised count, mean of last scores, a
thin progress bar; lessons still processing show the live job bar in the tile.
Anki imports appear under their own speakers, since the import creates **one
lesson per source video** (from asbplayer's Source field; notes without a
source fall into a lesson named after the query). Tabs to Review, Stats and
Settings in the header.

### 7.5 Stats: three grains

- **Sentences**: lessons and sentences by last score, best score and trend;
  a "regressed" list where last is well below best.
- **Characters**: per character or toneless syllable, mean and trend across
  all sentences; most-missed syllables.
- **Tones**: mean per canonical tone over time (1–4 and neutral) and a tone-pair
  matrix (previous tone × tone), so sandhi contexts stand out.
Plus minutes and attempts per day. Charts follow the dark palette below.

### 7.6 Visual style

Dark studio: near-black backgrounds, cool greys, reference in blue, you in
amber, scores in green / orange / red, no gamification. Hanzi in Noto Sans SC,
pinyin and UI in a humanist sans. A light theme is not in v1.

### 7.7 Yomitan-compatible rendering (hard requirement)

Yomitan scans real DOM text nodes with caret ranges. Therefore the sentence is
rendered as:

```html
<p lang="zh" class="sentence">
  <ruby>我<rt>wǒ</rt></ruby><ruby>今天<rt>jīntiān</rt></ruby>…
</p>
```

- One `<ruby>` per **word** (from `words_json`), never per character.
- Pinyin lives in `<rt>` (Yomitan skips it); the pinyin toggle hides the `<rt>`
  layer with CSS, it does not restructure the DOM.
- No per-character spans, no shadow DOM, no canvas text, no
  `user-select: none` on the sentence. Scoring colours go in the separate
  character row, not on the sentence.
- Scanning `今天` must pop CC-CEDICT with pinyin; verified manually in Phase 1.

---

## 8. Anki integration

All AnkiConnect calls are made from the browser (same host as Anki). Default
URL `http://127.0.0.1:8765`. First use calls `requestPermission`; the
settings page shows the instruction to add the app origin to
`webCorsOriginList` if that is denied.

### 8.1 Import (Phase 1)

Settings: one or more named **import queries**, e.g. `deck:Mining
tag:asbplayer`, `rated:1` (reviewed today), with a field mapping chosen from
`modelFieldNames`: sentence (required), audio (required), translation,
source, url. Import flow:

1. `findNotes(query)` → `notesInfo` → for each note, strip HTML from the
   sentence, parse `[sound:name]` from the audio field, `retrieveMediaFile`.
2. `POST /lessons/anki` with `{query_name, notes: [{note_id, text,
   translation, source, url, audio_b64, filename}]}`.
3. Backend groups notes by the video name parsed from the source field and
   creates or updates **one lesson per source video** (notes without a source
   go to a lesson named after the query); new notes are appended on re-import.
   It runs opencc, alignment, pinyin and clips; the note audio is the
   reference clip; `speaker` is the video's channel or uploader when the
   source or URL field reveals it, otherwise the video name.

### 8.2 Export (Phase 1)

"Send to Anki" on any segment builds an `addNote` for the configured note
type: sentence (hanzi), pinyin, translation, audio as inline base64 mp3 from
`GET /segments/{id}/audio?fmt=mp3`, tags `shadow`. Duplicates are allowed
only when the user confirms. The Review page offers the same action in bulk,
so Anki is the spaced-repetition layer; the app does not implement one.

### 8.3 asbplayer live proxy (Phase 4)

Backend runs a WebSocket server on `127.0.0.1:8766` and an AnkiConnect proxy
on the same port, forwarding to Anki on the Windows host (requires WSL mirrored
networking or AnkiConnect `webBindAddress` change). Intercepted `addNote` calls
create a segment in a rolling "Mined today" lesson with the clip asbplayer
recorded. `get-subtitles` lets a lesson be created from the cue list of the
video asbplayer has open, skipping ASR.

---

## 9. API

```
POST   /lessons                      multipart file (+ subtitles, title, speaker) → {job_id}
POST   /lessons/youtube              {url} → {job_id}                         (Phase 4)
POST   /lessons/anki                 {query_name, notes[]} → {job_id}
GET    /jobs/{id}/events             SSE progress
GET    /lessons                      list with status and practice stats
GET    /lessons/{id}                 lesson + segments (incl. words_json, ref_alignment_json)
DELETE /lessons/{id}
PATCH  /lessons/{id}                 {title, speaker}
GET    /segments/{id}/audio?fmt=opus|wav|mp3
POST   /segments/{id}/attempts       multipart WAV + {session_id, mode} → attempt + score
GET    /segments/{id}/attempts       history
GET    /attempts/{id}/audio
PATCH  /segments/{id}                {difficulty_flag, text}  (text edit re-runs align + enrich)
POST   /segments/{id}/resplit        {at_char_index} → two segments (time from ref alignment)
POST   /segments/{id}/merge-next
POST   /sessions                     {lesson_id, mode} → session
PATCH  /sessions/{id}                {ended: true}  (server stamps ended_at)
GET    /lessons/{id}/stats          per-segment last/best/trend, lesson mean per session
GET    /stats/activity               minutes/day, attempts/day
GET    /stats/sentences              last vs best across lessons, regressed list
GET    /stats/syllables              per character / toneless syllable means and trends
GET    /stats/tones                  per-tone means over time, tone-pair matrix
GET    /health                       models loaded, device, versions
```

---

## 10. Config (`config.toml`)

```toml
[server]
host = "127.0.0.1"
port = 8000

[models]
device = "auto"                     # auto | cuda | cpu
asr = "iic/speech_paraformer-large-vad-punc_asr_nat-zh-cn-16k-common-vocab8404-pytorch"
aligner = "auto"                    # auto → qwen3_fa on cuda, mms_fa on cpu | qwen3_fa | mms_fa | mfa
gop_model = "wbbbbb/wav2vec2-large-chinese-zh-cn"

[llm]
model = "claude-sonnet-5-5"
effort = "low"
rectify = true
translate = true

[segmentation]
min_chars = 6
max_chars = 25
pad_ms = 120

[scoring]
tone_weight = 0.5
dtw_band = 4
f0_floor = 60
f0_ceiling = 500
normalise_span = true
min_voiced_frames = 4
gop_margin = 2.0
min_duration_ratio = 0.4

[practice]
hide_text_while_recording = true
chorus_passes = 5
flow_gap_factor = 1.1
move_on_after = 4

[youtube]
enabled = false
cookies_file = ""

[anki]
default_url = "http://127.0.0.1:8765"
```

---

## 11. Testing and fixtures

- **Reference fixtures**: 30 fixed sentences synthesised once with
  Kokoro-82M-v1.1-zh (offline), committed as WAVs. 20 of them hand-labelled
  for syllable boundaries in Praat (TextGrids committed) for the aligner
  bake-off.
- **Synthetic learner attempts**: (a) another Kokoro voice → high score;
  (b) pitch flattened with parselmouth `Manipulation` / constant `PitchTier`
  → tone score drops, GOP stays high; (c) one syllable cut out → that
  syllable `missing`.
- **Aligner bake-off** (Phase 2 entry gate): mean absolute boundary error of
  `qwen3_fa`, `mms_fa`, `ctc-forced-aligner`, and the GOP model via
  `torchaudio.functional.forced_align`, against the TextGrids. Pick the
  default by error; keep the interface.
- **Rectification**: unit tests on hand-made character lists for coverage,
  contiguity, edit-distance and fallback; one test against a cached API
  response. No network in tests.
- **Anki import**: tests against recorded `notesInfo` JSON and a sample mp3.
- **Flow slicing**: unit tests for schedule → slice times with slack and VAD
  trim.
- **Yomitan**: manual checklist in Phase 1 acceptance (scan a multi-character
  word with pinyin on and off).

---

## 12. Build phases (each independently useful)

**Phase 0 — skeleton.** Repo layout, FastAPI `/health`, Vite app, SQLite,
ffmpeg wrapper, config loader, `make dev`, docker-compose optional.

**Phase 1 — loop without scoring.** Upload ingest through Paraformer,
rectification, alignment and clips; Anki import and export; practice page
with Echo, Chorus, Flow and Guided modes, back-to-back playback, toggles,
auto-hide text, flags, manual edit / resplit / merge; Yomitan-compatible
rendering; library by speaker. *Daily-usable milestone.* Flow mode in this
phase records and lets you replay per sentence; no scores yet.

**Phase 2 — tone.** Aligner bake-off; learner alignment and quality gate; F0,
per-syllable tone score, sentence contour overlay; attempt history; per-tone
stats; calibration notebook on your own recordings.

**Phase 3 — segmental.** GOP from the CTC model, baseline from the reference,
character row, most-missed syllables.

**Phase 4 — polish and integrations.** YouTube ingest with cookies, asbplayer
live proxy, review queue bulk export, MFA option if the bake-off shows
boundary error still matters, session stats.

Each phase gets its own implementation plan.

---

## 13. Non-goals for v1

- Multi-user accounts, auth, cloud deployment.
- Browser extension or in-page YouTube overlay.
- Learner-corpus-trained pronunciation models; the reference recording is the
  teacher.
- Spaced repetition and vocabulary inside the app; Anki does that.
- Dictionary lookup inside the app; Yomitan does that.
- Languages other than Mandarin.

## 14. Defaults chosen where the review left options

- Default aligner on GPU is `qwen3_fa`; the Phase 2 bake-off may flip it.
- Anki-sourced lessons keep the mp3 clip as is; no re-encoding beyond the
  16 kHz WAV copy used for scoring.
- Chorus records only the last pass. Recording every pass is a later option.
- Flow default sub-mode is `after`; `along` is a toggle.
