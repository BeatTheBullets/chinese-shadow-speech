# Chinese Shadowing Practice Tool — Build Spec

Brief for Claude Code. Build a self-hosted, web-based Mandarin shadowing tool
modelled on Trancy's shadowing mode: one sentence at a time, play → record →
auto-playback → per-character score, plus tone-contour feedback that Trancy
lacks. Single user, runs locally or on a home/lab server.

Priorities in order: (1) a practice loop that is pleasant enough to use for 20
minutes a day, (2) clean sentence segmentation, (3) scoring. A tool with no
scoring but a great loop is useful on day one; scoring with a clunky loop is not.

---

## 1. Architecture

```
┌──────────────────────┐   HTTP/SSE    ┌──────────────────────────────┐
│  Frontend (SPA)      │ ───────────▶  │  FastAPI backend (Python)    │
│  React + Vite + TS   │               │  - ingestion jobs             │
│  MediaRecorder, Web  │ ◀───────────  │  - transcription + segment    │
│  Audio, canvas plots │   JSON/audio  │  - scoring service            │
└──────────────────────┘               │  - SQLite + files on disk     │
                                       └──────────────────────────────┘
                                          │ faster-whisper (ASR)
                                          │ wav2vec2 CTC (alignment / ASR)
                                          │ parselmouth (F0)
                                          │ yt-dlp, ffmpeg
```

One repo, two packages:

```
shadow/
  backend/            Python 3.11+, FastAPI, uv or pip
    shadow/
      api/            routers
      ingest/         yt-dlp, ffmpeg, whisper, rectify, pinyin
      scoring/        align, asr_diff, tone, prosody
      store/          SQLite (sqlmodel), file layout
      models.py       pydantic schemas (single source of truth for API types)
    tests/
  frontend/           React + Vite + TypeScript, Tailwind
  data/               runtime: lessons/, attempts/, models/ (gitignored)
  docker-compose.yml  optional; backend works bare-metal too (GPU optional)
```

Why not fork Hibiki (JulianPJ/Shadowing)? It is the closest existing project,
but it is Next.js with the ASR bolted on as a sidecar, and all the hard work
here is Python. Use Hibiki as a UX reference (segmentation heuristics,
shadowing-mode pause behaviour), not as a code base.

GPU: everything must run on CPU (faster-whisper int8, small CTC model). Use
CUDA automatically if present. Target: a 10-minute video ingests in under 5
minutes on CPU; a single attempt scores in under 1.5 s.

---

## 2. Ingestion pipeline

Input: a YouTube URL **or** an uploaded audio/video file, optional transcript
file (SRT/VTT/plain text).

### 2.1 Fetch and normalise

- `yt-dlp` → best audio → `ffmpeg` → 16 kHz mono WAV (`source.wav`). Keep the
  video id, title, channel, duration, thumbnail URL as metadata.
- Also pull uploader-provided `zh` subtitles if they exist (`--write-subs`,
  not `--write-auto-subs`). Human subtitles beat Whisper; auto-subs do not.
- Uploads: same ffmpeg normalisation.

### 2.2 Transcription

- `faster-whisper`, model `large-v3-turbo` (configurable; `small` for quick
  tests), `language="zh"`, `word_timestamps=True`, `vad_filter=True`,
  `beam_size=5`, `initial_prompt` with a few simplified-Chinese sentences with
  punctuation (nudges Whisper toward punctuated, simplified output).
- Output: a flat list of timed tokens `{i, text, start, end}` across the whole
  file. For Chinese, Whisper's "words" are 1–3 characters; treat them as
  opaque timed tokens.
- Run `opencc` (t2s) on everything so the whole app is simplified-only.
- If uploader subtitles exist: use *their* text but still run Whisper to get
  token-level timing, then align subtitle text to Whisper tokens by character
  edit distance (`rapidfuzz`) to inherit timings. Fall back to Whisper text if
  alignment coverage < 80 %.

### 2.3 Sentence segmentation

Split the timed tokens into shadowable sentences at sentence punctuation
(。！？；), clause punctuation (，、：) and Whisper segment ends. Boundaries are
token index ranges, so timing is never detached:
`sentence.start = tokens[from].start`, `sentence.end = tokens[to].end`, then
pad ±120 ms and clamp to neighbours. Wrong characters are fixed by hand
(manual split/edit, Phase 1); syllable timing comes from forced alignment
(§4.1), so character edits inside a sentence cost nothing.

### 2.4 Enrichment per sentence

- `pinyin`: `pypinyin` with `Style.TONE` and `heteronym=False`; also store
  tone numbers per syllable for the tone scorer (`Style.TONE3`). Mark
  neutral-tone syllables (tone 5/0). Known limitation: pypinyin gives
  dictionary tones, not sandhi — the tone scorer compares against the native
  *recording*, not against these numbers, so this is display-only.
- `clip`: `ffmpeg` cut of the padded sentence → `data/lessons/{id}/clips/{n}.wav`
  (16 kHz) plus an Opus copy for the browser.

### 2.5 Job model

`POST /lessons` returns `{job_id}`; progress streamed over SSE
(`GET /jobs/{id}/events`) with stages: `download`, `transcribe`, `rectify`,
`enrich`, `done|error`, each with a 0–1 fraction. Jobs run in a background
worker (simple `asyncio` queue + thread pool is fine; no Celery).

---

## 3. Data model

```python
class Lesson:   id, title, source_url, source_type, duration_s, channel,
                created_at, status, meta_json
class Segment:  id, lesson_id, idx, start_s, end_s, text, pinyin,
                tones (list[int]), translation, difficulty_flag,
                clip_wav_path, clip_opus_path
class Attempt:  id, segment_id, created_at, audio_path, score_json,
                duration_s
class Session:  id, started_at, ended_at, lesson_id, attempts_count
```

SQLite via `sqlmodel`; audio on disk. Keep every attempt — the history view
and "which sentences do I keep failing" depend on it.

---

## 4. Scoring service

Input for every attempt: the expected text, the native reference clip, the
learner recording. Because all three are known, use **forced alignment**, not
open-vocabulary recognition, wherever possible. Return one JSON object:

```json
{
  "overall": 0.82,
  "chars": [
    {"ch": "我", "pinyin": "wǒ", "status": "ok|mispronounced|missing|extra",
     "tone_score": 0.91, "seg_score": 0.88,
     "ref_f0": [...20 floats semitones...], "usr_f0": [...],
     "ref_dur": 0.21, "usr_dur": 0.29}
  ],
  "tone_overall": 0.78, "segmental_overall": 0.86,
  "rate_ratio": 1.18,
  "warnings": ["low_voicing_ratio"]
}
```

### 4.1 Syllable alignment (shared by everything below)

Align the expected syllable sequence to audio for **both** reference clip and
learner recording. Two implementations behind one interface:

1. **Default: `torchaudio` MMS forced aligner** (`MMS_FA` bundle). Multilingual
   CTC; pass the expected text as romanised pinyin *without tones*
   (`Style.NORMAL`), one token per syllable. Pip-only, CPU-OK, ~300 ms per
   sentence. Returns syllable start/end.
2. **Optional: Montreal Forced Aligner** with the Mandarin (pinyin) acoustic
   model and dictionary — more precise boundaries, heavier install (conda).
   Behind a config flag; not required for v1.

Cache the reference alignment per segment at ingest time.

Quality gate: if alignment confidence is low or the learner audio is < 40 % of
the reference duration, mark the whole attempt `missing`-heavy rather than
emitting nonsense per-character scores.

### 4.2 Segmental (initials/finals) scoring → Trancy-style green/orange/grey

v1 approach — ASR diff:
- Run a **CTC Chinese ASR model with no language model** on the learner clip
  (e.g. a `wav2vec2-large-xlsr-53` Chinese fine-tune from the HF hub; config
  key `asr_model`). Avoid Whisper here: its decoder auto-corrects learner
  errors, which is the opposite of what a scorer needs.
- Convert recognised characters and expected characters to toneless pinyin,
  align with character-level Needleman–Wunsch (`rapidfuzz` / own
  implementation). Match → `ok`, substitution → `mispronounced`, gap in user
  → `missing`, gap in expected → `extra`.
- Because many characters are homophones, compare on pinyin, never on
  characters.

v2 approach (later) — GOP: take the CTC posteriors from the forced alignment
and compute goodness-of-pronunciation per syllable (log posterior of the
expected token vs. best competing token within the syllable span). This gives
a continuous `seg_score` instead of a 3-way label and does not depend on the
ASR making the same mistake you did. Implement only once v1 is in daily use.

### 4.3 Tone scoring

The reference recording *is* the ground truth, so no learner-trained tone
model is needed. Per syllable:

1. F0 track for the whole clip with `parselmouth` (Praat autocorrelation,
   time step 10 ms, floor/ceiling 60–500 Hz; retry with a wider range if
   voicing ratio < 50 %).
2. Slice per syllable using the alignment from §4.1. Trim the first and last
   15 % of each syllable (onset consonants and transitions corrupt the
   contour).
3. Convert to semitones relative to that speaker's **median F0 over the whole
   sentence** — this removes pitch range differences between you and the
   reference speaker. Optionally z-normalise as well (config).
4. Interpolate voiced frames to a fixed 20 points. If < 4 voiced frames,
   mark the syllable `unvoiced` and skip (common for neutral tones and short
   syllables — report, don't penalise).
5. Score = `1 - clamp(DTW(ref, usr) / norm, 0, 1)` with a Sakoe–Chiba band of
   4 points, plus a slope-sign agreement term for tones 2/4 (rising vs.
   falling is the error that matters most). Weights in config; calibrate by
   hand against a dozen of your own recordings.
6. Return both contours so the frontend can overlay them. The overlay is the
   primary feedback; the number is secondary.

Also compute sentence-level pitch range and declination so the UI can say
"flat" vs. "exaggerated" at a glance (just two numbers, no model).

### 4.4 Prosody / timing

- `rate_ratio = usr_duration / ref_duration` for the sentence.
- Per-syllable duration ratios (from alignment) → highlight syllables held
  > 1.8× or < 0.5× the reference.

### 4.5 Test fixtures

- Generate reference clips with a Chinese TTS (`edge-tts` zh voices) for 30
  fixed sentences, check in the WAVs.
- Synthetic learner attempts: (a) the same TTS with a different voice =
  should score high; (b) pitch-flattened version (`librosa` pitch shift +
  flatten) = tone score must drop, segmental must stay high; (c) one syllable
  cut out = that character must be `missing`.
- Segmentation: unit tests on hand-made token lists for splitting at
  punctuation and segment ends (no network in CI).

---

## 5. API

```
POST   /lessons                     {url} | multipart file (+ optional subtitles) → {job_id}
GET    /jobs/{id}/events            SSE progress
GET    /lessons                     list with status, progress stats
GET    /lessons/{id}                lesson + segments
DELETE /lessons/{id}
GET    /segments/{id}/audio?fmt=opus|wav
POST   /segments/{id}/attempts      multipart audio (webm/opus or wav) → score JSON + attempt id
GET    /segments/{id}/attempts      history
GET    /attempts/{id}/audio
PATCH  /segments/{id}               {difficulty_flag, text, pinyin}  (manual fixes)
POST   /segments/{id}/resplit       {at_char_index} → two segments (manual split)
POST   /sessions / PATCH /sessions/{id}
GET    /stats                       minutes practised per day, weakest tones, flagged segments
GET    /health                      models loaded, device, versions
```

Audio from the browser arrives as `audio/webm;codecs=opus`; convert with
ffmpeg to 16 kHz WAV before scoring. Store both.

---

## 6. Frontend — the practice loop

Single page per lesson, keyboard-first, works on a laptop and a phone browser.

Layout:
- Top: small video thumbnail / title, progress `12 / 48`, session timer that
  turns amber at 20 min (the article's advice — shadowing is tiring).
- Centre: the current sentence, large. Three independent toggles, remembered
  per lesson: **hanzi**, **pinyin**, **translation**. Default for a new
  lesson: hanzi + pinyin on, translation off. "Ear mode" = all three off.
- Below: character row rendered after scoring — green / orange / grey per
  character, hover shows pinyin and tone score. Under it the **tone overlay**:
  one small panel per syllable with the reference contour (solid) and yours
  (dashed) on a semitone axis, plus the canonical tone number.
- Bottom bar: ◀ prev · ▶ play (Space) · ● record (Enter) · speed 0.6–1.0 ·
  ↻ repeat count · next ▶ (→) · flag ⚑ (F).

Behaviour:
- Space plays the reference; Enter starts recording; Enter again (or silence
  > 1.2 s after speech, via a simple RMS VAD in the browser) stops it.
- After stopping: auto-play **reference → your attempt** back-to-back (as the
  article recommends), while the score request is in flight. Show score when
  it arrives; never block playback on scoring.
- Optional "guided" mode implementing the article's progression per sentence:
  listen ×1 → whisper along (text visible) → record (text hidden). Config.
- Auto-advance after N attempts with overall ≥ threshold (default off; the
  article warns against obsessing over a single sentence — surface a "move on"
  hint after 4 attempts instead).
- Record/playback latency matters more than anything visual. Decode clips to
  AudioBuffers up front; preload next segment.

Other pages:
- Library: lessons grouped by channel (supports the "language parent" idea —
  shadow one speaker consistently). Add-by-URL box with live job progress.
- Review: segments flagged or with mean score below threshold, oldest first.
- Stats: minutes/day, attempts/day, per-tone mean score over time (bar per
  tone 1–4), most-missed syllables.

Visual direction: calm, high-contrast, no gamification confetti. Chinese text
set in a proper CJK font (Noto Sans SC), pinyin in a humanist sans.

---

## 7. Build phases (each independently useful)

**Phase 0 — skeleton.** Repo layout, FastAPI with `/health`, Vite app, SQLite,
ffmpeg + yt-dlp wrappers, docker-compose, `make dev`.

**Phase 1 — loop without scoring.** Ingestion through segmentation and
clips; practice page with play/record/back-to-back playback, toggles, flags,
manual split/edit. *Daily-usable milestone.*

**Phase 2 — segmental scoring.** Forced alignment service, CTC ASR, pinyin
diff, green/orange/grey row. Attempt history.

**Phase 3 — tone scoring.** F0 extraction, per-syllable contours, DTW score,
overlay panels, per-tone stats. Calibration notebook using your own
recordings.

**Phase 4 — polish.** Guided mode, review queue, session stats, library by
channel, GOP (§4.2 v2), MFA option.

---

## 8. Config (`config.toml`)

```toml
[models]
whisper = "large-v3-turbo"      # or "small" for dev
asr_ctc = "<hf repo id for Chinese wav2vec2 CTC>"
aligner = "mms_fa"              # or "mfa"
device = "auto"
[scoring]
tone_weight = 0.5
dtw_band = 4
f0_floor = 60
f0_ceiling = 500
[segmentation]
min_chars = 6
max_chars = 25
```

---

## 9. Non-goals for v1

- Multi-user accounts, auth, cloud deployment.
- Browser extension / in-page YouTube overlay (Trancy's approach). Download
  the audio instead; simpler and works offline.
- Learner-corpus-trained pronunciation models. The reference recording is the
  teacher.
- Spaced repetition / vocabulary. This is a speaking tool.

## 10. Open decisions

- Chinese CTC ASR model choice (§4.2): pick after a 30-minute bake-off on the
  TTS fixtures — accuracy on clean speech matters less than *not*
  autocorrecting.
- Whether tone normalisation should be sentence-median or per-syllable-window;
  start with sentence-median, revisit after calibration.
- Hosting: laptop-local vs. lab server with GPU. Design for both; default to
  CPU int8 so nothing depends on the server.
