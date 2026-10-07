# chinese-shadow-speech — a Mandarin shadowing studio

**chinese-shadow-speech** turns any Chinese YouTube video or audio file into a shadowing lesson. It cuts the speech into short
sentences, aligns every character to the audio, adds pinyin and a translation, and gives you four ways to practise
speaking along. Everything you record is kept. The sentences you have practised go to Anki as listening cards.

It runs locally: a Python backend in WSL2/Linux with GPU speech models, and a React app in the browser (built for
Brave + Yomitan on Windows).

![Flow mode: the sentence fills with colour in time with the speaker, with count-in dots before your turn](docs/screenshots/flow-listen.png)

> Screenshots show lessons made from Mandarin Click's HSK1 stories.

---

## Contents

- [What it does](#what-it-does)
- [How a lesson is made](#how-a-lesson-is-made)
- [Keyboard shortcuts](#keyboard-shortcuts)
- [Getting started](#getting-started)
- [Development](#development)
- [Roadmap](#roadmap)

---

## What it does

### Lessons from YouTube or your own files

Paste a YouTube link into the Library, or click the **→ chinese-shadow-speech** bookmarklet on a YouTube page. You can also
drop an audio or video file, with or without a subtitle file. A few minutes later the lesson is ready:

- The whole video becomes one lesson, split into sentences of about 6–25 characters.
- Long videos are split into **passages** of about 2–3 minutes. YouTube chapters are used when the video has them.
- Lessons are grouped by speaker (the YouTube channel). Each tile shows how many sentences and passages you have practised.

![Library](docs/screenshots/library.png)

When a YouTube video has real Chinese subtitles, their text is used, with the timing taken from the speech
recogniser. Machine-translated auto-captions are refused, and so are subtitles that don't match the audio. A plain
`.txt` transcript works too.

### Four practice modes

| Mode | What you do |
|---|---|
| **Echo** | One sentence at a time: listen, then repeat it on your own. You hear the original and your take back to back. |
| **Chorus** | Speak at the same time as the sentence, several times in a row. The last pass is recorded. |
| **Flow** | Shadow a whole passage without stopping. *After*: each sentence plays, then you repeat it in the pause. *Along*: speak at the same time as the audio (use headphones). |
| **Guided** | Four steps per sentence: listen → whisper along with the text → say it with the text hidden → next. |

The stage shows the sentence with pinyin and a translation. Below it, a **two-track feedback block** puts the
reference and your take on the same time scale, with a cell per syllable. Click a cell to hear that syllable once.

![Echo mode: the cue line says what to do, the reference is wiping](docs/screenshots/echo-listen.png)

### It always tells you what to do

- **Cue line:** above the sentence it always shows what to do now, in the track colours: 🎧 **Listen**,
  🗣 **Your turn — speak now**, 🎤 **Speak along**, ✓ **Done**.
- **Mic level meter:** shows that your voice is being picked up.
- **Karaoke cues:**
  - The sentence fills with colour in time with the speaker.
  - During your turn, a fainter amber wipe runs at the speaker's pace.
  - Count-in dots ● ● ● appear before you have to start.
- **Flow extras:** a preview of the next line and a bar that shrinks over your speaking window.

![Echo, your turn: amber pacing wipe and mic meter](docs/screenshots/echo-record.png)

![Flow, your turn: the turn bar shrinks while you speak](docs/screenshots/flow-turn.png)

Hover over a mode tab for a one-line explanation, or press `?` for the full help. The help also opens by itself on your first visit.

![Help overlay](docs/screenshots/help.png)

### Listening back

- Every take is kept. When you reopen a lesson, **R** plays your latest take of the current sentence and
  **Space** plays the original.
- In Flow mode the setup panel offers your **last runs**. **▶ replay** plays each sentence as original → you.
- The **reference volume** is adjustable. While you speak along, in Chorus and Flow *along*, the reference drops to
  a quieter **guide level**, 50 % by default.

![Flow setup with the last run ready to replay](docs/screenshots/flow-setup.png)

### Fix the text when the machine got it wrong

From the lesson drawer you can **edit** a sentence's text, **split** it in two, or **merge** it with the next one.
Each change re-aligns the audio, rebuilds the pinyin and translation, and cuts new clips.

### Works with Yomitan

The sentence is ordinary text with one `<ruby>` per word, so the
[Yomitan](https://github.com/yomidevs/yomitan) pop-up dictionary works on it (hold Shift and hover). The karaoke wipe
is drawn as a separate layer and never changes the sentence's markup.

### Anki listening cards

Speaking happens in the app; Anki is used for **listening** review.

- **One-click setup:** Settings → **Set up chinese-shadow-speech deck** creates a deck and a *Shadow Listening* note type.
  The front is the audio only ("What did you hear?"). The back shows the hanzi, pinyin, translation and a link back
  to the moment in the YouTube video.
- **End of session:** a dialog offers the sentences you practised. Fillers like 嗯, 对 and 好的 start unticked.
- **Nothing gets lost:** if Anki was closed, Review lists everything **practised but not yet in Anki**.

![End-of-session dialog](docs/screenshots/export-dialog.png)

![Review: flagged sentences and practised sentences not yet in Anki](docs/screenshots/review.png)

### Stats

Minutes and attempts per day for the last 30 days. Per-sentence, per-character and per-tone scores arrive with tone
scoring (see the [Roadmap](#roadmap)).

![Stats](docs/screenshots/stats.png)

### Settings

You can set:
- the AnkiConnect address, import queries and the export note type;
- practice preferences: hide the text while recording, chorus passes, the Flow pause length, the "move on" hint and the default speed;
- the YouTube bookmarklet.

![Settings](docs/screenshots/settings.png)

---

## How a lesson is made

```
YouTube link / file
   │  yt-dlp (audio only) · ffmpeg → 16 kHz mono WAV
   ▼
Speech recognition          FunASR Paraformer-zh, per-character timestamps
   │  + Chinese subtitles   text from the subtitles, timing from the recogniser
   ▼
Sentences                   Claude (optional) splits into 6–25-character sentences and fixes ASR errors;
   │                        subtitle text is locked, only punctuation and boundaries may change
   ▼
Forced alignment            MMS_FA per sentence, repaired against the recogniser's character times
   ▼
Enrichment                  jieba words + pypinyin (tone sandhi), translation, Opus/WAV clips, passages
```

All models run locally; the default device is the GPU (CUDA), with a CPU fallback. The only network calls are the
YouTube download, the one-time model downloads, and the optional Anthropic API, used to split sentences and
translate. Without an API key, sentences are split at punctuation and there are no translations.

---

## Keyboard shortcuts

| Key | Action |
|---|---|
| `Space` | Play the reference |
| `Enter` | Record / stop (Echo), start Chorus or Flow, next Guided step |
| `C` | Chorus |
| `←` `→` | Previous / next sentence |
| `R` | Replay your take |
| `S` | 0.75× speed |
| `T` `P` `E` | Hide or show hanzi, pinyin, translation |
| `F` | Flag the sentence for Review |
| `A` | Send to Anki |
| `L` | Collapse the lesson drawer |
| `?` | Help |

---

## Getting started

### Requirements

- WSL2 or Linux, with an NVIDIA GPU whose driver supports **CUDA 12.6** (Windows driver ≥ 560). A CPU works too, but slower.
- [uv](https://docs.astral.sh/uv/) (Python 3.12 is installed by uv), Node 20, ffmpeg.
- Optional:
  - [Deno](https://deno.com), which recent yt-dlp versions need for YouTube.
  - An `ANTHROPIC_API_KEY`, for sentence splitting and translations.
  - Anki with [AnkiConnect](https://ankiweb.net/shared/info/2055492159).

### Install and run

```bash
cd backend && uv sync --extra dev --extra models   # PyTorch (cu126), FunASR, aligners
cd ../frontend && npm install
export ANTHROPIC_API_KEY=...                       # optional
cd .. && make dev                                  # backend on :8000, frontend on :5173
```

Open **http://localhost:5173**. The first lesson downloads the speech models (~1 GB Paraformer, ~1.2 GB MMS_FA). Run
`cd backend && uv run pytest -m models` once to check them. `curl -s localhost:8000/health` should report
`"device": "cuda"`.

Always pass both extras to `uv sync`. A plain `uv sync` uninstalls the model packages.

### Connect Anki

In Anki: Tools → Add-ons → AnkiConnect → Config, add the app to the allowed origins, and restart Anki:

```json
"webCorsOriginList": ["http://localhost", "http://localhost:5173", "http://127.0.0.1:8000"]
```

Then in the app: Settings → **Connect**, and **Set up chinese-shadow-speech deck**.

### Production build

```bash
cd frontend && npm run build && cd .. && make backend   # the backend serves the app on http://127.0.0.1:8000
```

[docs/running.md](docs/running.md) covers CPU-only use, Docker, YouTube cookies (for age-restricted videos and bot
checks), Deno and updating yt-dlp.

---

## Development

```bash
make test        # backend pytest, frontend vitest, eslint and the TypeScript type-check
```

Tests never need a GPU, network or model download. Every external model and service sits behind an interface with a
fake implementation.

| Path | What's there |
|---|---|
| `backend/shadow/ingest/` | download, ASR, subtitle alignment, rectification, forced alignment and repair, enrichment, passages |
| `backend/shadow/api/` | FastAPI routes: lessons, segments, attempts, sessions, review, stats, Anki import |
| `backend/shadow/store/` | SQLModel tables (SQLite) and the on-disk audio layout |
| `frontend/src/pages/` | Library, Practice (with Flow), Review, Stats, Settings |
| `frontend/src/lib/` | pure logic: cues, karaoke timing, flow scheduling, passages, keys |
| `frontend/src/audio/` | clip player, AudioWorklet recorder (16 kHz PCM WAV), VAD |
| `docs/superpowers/specs/` | the design: [main spec](docs/superpowers/specs/2026-10-03-shadowing-tool-design.md), [YouTube/passages/guidance addendum](docs/superpowers/specs/2026-10-07-youtube-passages-guidance-design.md) |
| `docs/superpowers/plans/` | the implementation plans each phase was built from |
| `docs/phase1-acceptance.md` | the manual checklist for things only a real browser, mic and Anki can verify |

---

## Roadmap

**Built:**
- **Phase 0–1:** the pipeline, the four practice modes, the Anki bridge and Yomitan rendering.
- **Phase 1.5:** YouTube lessons, passages, the guidance and karaoke cues, volume, listening cards, and recordings that come back when you reopen a lesson.

### Next: Phase 2 — tone scoring

The feedback cells already have a place for a score. Phase 2 fills it:

- **Learner alignment:** your recording is aligned to the sentence, with a quality gate that skips takes that are
  too quiet, clipped or the wrong sentence instead of scoring them.
- **Pitch tracking:** pitch is measured on both tracks with Praat (`parselmouth`) and normalised to each speaker's own
  range, so a lower voice isn't penalised.
- **A tone score per syllable:** your pitch curve is compared with the reference's, and the cells turn green, orange
  or red. A contour overlay shows both curves.
- **Stats** per character, per tone and per tone pair (for example 3-3 sandhi), across all your attempts.
- **Calibration** against your own recordings, so "green" matches what sounds right.

### Phase 3 — consonants and vowels

Per-syllable pronunciation feedback (goodness of pronunciation from a Chinese CTC model), so you see *which*
syllables were mispronounced, not just which tones. It also adds a "most-missed syllables" list.

### Phase 4 — polish

Session statistics, and an optional Montreal Forced Aligner if timing still needs to be more precise.

### Known rough edges

- Two Flow runs that finish within a minute of each other are listed as one run.
- On YouTube auto-captions without punctuation, some sentence boundaries land mid-phrase. **Edit / Split / Merge**
  in the drawer fixes them.
- The Library page polls while a lesson is processing; very large libraries may want a smarter refresh.

---

*No licence has been chosen yet.*
