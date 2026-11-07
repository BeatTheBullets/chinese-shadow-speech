# Development

How to run chinese-shadow-speech from source, test it, and find your way around the code. To just use the app on
Windows, see the [README](../README.MD#install-on-windows).

## Run from source

**Requirements:** Linux or WSL2, [uv](https://docs.astral.sh/uv/) (it installs Python 3.12), Node 20 and ffmpeg. An
NVIDIA GPU with a driver for **CUDA 12.6** (Windows driver ≥ 560 under WSL2) makes it fast; without one it runs on the
CPU (see [running.md](running.md#cpu-only) for the 8-bit settings an 8 GB machine needs). Optional:
[Deno](https://deno.com), which recent yt-dlp versions need for YouTube, and Anki with
[AnkiConnect](https://ankiweb.net/shared/info/2055492159).

```bash
cd backend && uv sync --extra dev --extra models   # PyTorch (CUDA on Linux, CPU on Windows), FunASR, aligners
cd ../frontend && npm install
cd .. && make dev                                  # backend on :8000, frontend on :5173
```

Open **http://localhost:5173**. The first lesson downloads the speech models. Run `cd backend && uv run pytest -m models`
once to check them; `curl -s localhost:8000/health` should report `"device": "cuda"` on a GPU machine.

Always pass both extras to `uv sync`: a plain `uv sync` uninstalls the model packages.

**Production build:** `cd frontend && npm run build && cd .. && make backend` serves the app on http://127.0.0.1:8000.

[running.md](running.md) covers the configuration (`config.toml`), CPU-only use, Docker, YouTube cookies, Deno and
updating yt-dlp.

## Tests

```bash
make test        # backend pytest, frontend vitest, eslint and the TypeScript type-check
cd backend && uv run pytest ../packaging/windows    # the Windows bootstrap and installer script
cd backend && uv run pytest -m models               # real-model smoke tests (downloads the models)
```

The default tests never need a GPU, network or model download: every model and external service sits behind an
interface with a fake. CI runs them on Linux and Windows and builds the Windows installer
(`.github/workflows/ci.yml`); a `vX.Y.Z` tag builds the installer for a GitHub Release (`release.yml`).

## The Windows package

`packaging/windows/build.ps1` builds the per-user Inno Setup installer. It bundles a standalone Python, uv, ffmpeg
and Deno (pinned with checksums in `versions.json`), the backend source and the built frontend. On the first start
`bootstrap.py` creates the Python environment with uv and runs `python -m shadow.laptop prepare`, which downloads the
models and stores their 8-bit copies, behind a progress page. Then `shadow/launcher.py` runs the server with a tray icon.
Design: [windows-laptop design](superpowers/specs/2026-10-22-windows-laptop-design.md); measurements:
[windows-acceptance.md](windows-acceptance.md).

## Where things are

| Path | What's there |
|---|---|
| `backend/shadow/ingest/` | download, speech recognition, subtitle alignment, sentence splitting, forced alignment and repair, enrichment, passages |
| `backend/shadow/scoring/` | pitch tracking, the tone model, syllable scoring, voice profile |
| `backend/shadow/scoring/sounds/` | wrong-sound detection: the character-CTC model, GOP and bad-pronunciation scores, fusion |
| `backend/shadow/api/` | FastAPI routes: lessons, segments, attempts, sessions, review, stats, drills, settings, Anki import |
| `backend/shadow/drill/` | drills: focus ranking and rotation, the cross-lesson queue, summaries |
| `backend/shadow/store/` | SQLModel tables (SQLite) and the on-disk audio layout |
| `backend/shadow/quant.py`, `laptop.py`, `launcher.py` | 8-bit models and CPU threads; the laptop config and `prepare`; the tray launcher |
| `backend/scripts/` | maintenance and measurement: `backfill_sounds.py`, `drop_failed_takes.py`, `rescore.py`, `tone_model.py`, `cpu_budget.py`, `int8_check.py`, `split_gate.py` |
| `frontend/src/pages/` | Library, Practice (with Flow), Review, Drill, Stats, Settings |
| `frontend/src/lib/` | pure logic: cues, karaoke timing, Flow scheduling, passages, keys, the drill step machine |
| `frontend/src/audio/` | clip player, AudioWorklet recorder (16 kHz PCM WAV), voice activity detection |
| `packaging/windows/` | the installer, first-run bootstrap and build script |
| `docs/superpowers/specs/`, `plans/` | the designs and the implementation plans each phase was built from |
| `docs/*-acceptance.md` | manual checklists for what only a real browser, microphone, Anki or laptop can verify |

## How a lesson is made

```
YouTube link / file
   │  yt-dlp (audio only) · ffmpeg → 16 kHz mono WAV
   ▼
Speech recognition          FunASR Paraformer-zh, per-character timestamps
   │  + Chinese subtitles   text from the subtitles, timing from the recogniser
   ▼
Sentences                   split at punctuation: the subtitles' own, or what the sherpa-onnx punctuation model adds
   ▼
Forced alignment            MMS_FA per sentence, repaired against the recogniser's character times
   ▼
Enrichment                  jieba words + pypinyin (tone sandhi), Opus/WAV clips, passages
```

A take is scored by aligning it to the sentence (MMS_FA), comparing pitch contours and a tone classifier on wav2vec2
features per syllable, checking initials and finals with a character-level CTC model, and checking the words with the
recogniser.

## Maintenance scripts

- `make backfill-sounds` (`ARGS="--dry-run"`, `ARGS="--data-dir DIR"`) adds sound results to older takes. Stop the
  backend and back up the database first.
- `backend/scripts/drop_failed_takes.py` (`--dry-run`, `--data-dir`) removes older takes the recording gates would now
  reject.
- Sound checking is tuned under `[sounds]` in `config.toml`, drills under `[drill]` (see the comments in
  `config.toml`).
