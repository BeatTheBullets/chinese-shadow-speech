# Running

## Dev (WSL2, GPU)
    cd backend && uv sync --extra dev --extra models      # pulls torch from the PyTorch cu126 index
    export ANTHROPIC_API_KEY=...                          # optional; without it rectification/translation are skipped
    cd .. && make dev

The GPU driver must support CUDA 12.6 (Windows NVIDIA driver >= 560).
First ingest downloads Paraformer-zh (~1 GB, ModelScope) and the MMS_FA aligner (~1.2 GB, torchaudio).
Before the first real ingest, smoke-test Paraformer and the aligners: `cd backend && uv run pytest -m models`.
Verify the GPU is seen: `curl -s localhost:8000/health` -> `"device": "cuda"`.

## CPU only
Set `[models] device = "cpu"` in config.toml; the aligner is MMS_FA on every device (`aligner = "qwen3_fa"` selects Qwen3 explicitly).

## Docker
    cd frontend && npm run build        # produces frontend/dist, which the image copies
    ANTHROPIC_API_KEY=... docker compose up --build

Serves the SPA and API on http://127.0.0.1:8000. The image is built without the `models` extra
(no torch), so it is for CPU / no-model use only; run the real models from the dev setup above.
Data lives in `./data`, config in `./config.toml` (mounted read-only).

## Tests
    make test                       # fakes only, no models
    cd backend && uv run pytest -m models   # real-model smoke tests

## YouTube
YouTube lessons are on by default (`[youtube] enabled = true`). Paste a link into the Library's "Paste a YouTube link"
field, or drag the "→ chinese-shadow-speech" bookmarklet from Settings to the Brave bookmarks bar and click it on a video page.
Videos longer than `[youtube] max_minutes` (default 90) are refused. Chinese subtitles are used when the video has
them (manual first, then auto-generated); otherwise the ASR text is used.

Cookies: age-restricted videos and YouTube's "confirm you're not a bot" check need your browser's YouTube cookies.
While signed in to YouTube, export them with a cookies.txt browser extension (Netscape format), save the file
somewhere private (e.g. `~/shadow-cookies.txt`), set `[youtube] cookies_file = "/home/<you>/shadow-cookies.txt"` in
config.toml and restart the backend. Cookies expire; export them again when the error comes back.

Deno: recent yt-dlp versions need a JavaScript runtime for YouTube. If a download fails mentioning a JS runtime or
Deno, install it (`curl -fsSL https://deno.land/install.sh | sh`) and make sure `deno` is on the PATH of the shell that
runs `make dev`.

Updating yt-dlp: YouTube changes often. When a lesson fails with "extraction failed, yt-dlp is probably outdated":

    cd backend && uv lock --upgrade-package yt-dlp && uv sync --extra dev --extra models

## Tone scoring
The tone model ships in `backend/shadow/scoring/models/` (`tone_v1.joblib` and `tone_v1.json`). It scores on the speech
model chinese-wav2vec2 (~380 MB from Hugging Face, MIT), which the backend loads in the background at start-up and
downloads the first time (needs the models extra); a take scored before that finishes waits for it.
If the download fails it is logged and the first scored take tries again. A missing or unreadable tone model file
is logged too and takes are then saved unscored ("Tone model missing").
`/health` reports `tone_model.loaded` and its version.

Retraining: `make tone-model LABELS=realised`. It downloads ~17.7 GB (AISHELL-3, OpenSLR SLR93, Apache-2.0) into
`data/corpora/aishell3` (the script's own estimate is ~19 GB with extraction), trains on 10 h of it with two
pitch-altered copies per utterance, takes ~1.5 h on the GPU and needs the models extra. The speech model
(chinese-wav2vec2, ~380 MB from Hugging Face, MIT) is downloaded on first use. Feature caches are kept under
`data/corpora/aishell3/`.

After a model or feature change run `make rescore`: it re-scores every stored take and writes
`data/reports/rescore-<date>.html`. `--probe` (run `cd backend && uv run python scripts/rescore.py --probe` directly; the make target takes no args) prints the percentiles used to pick the gate thresholds
(`min_rms_dbfs`, `min_align_conf`).

Voice profile: tones are judged against your own pitch range, which is learned from your most recent minute or so of voiced speech and keeps adapting as you practise.
Settings -> Voice profile shows it; **Reset voice profile** empties it (for a new mic or after a bad take) and the next
takes rebuild it.

Gate warnings (the take is always saved, it is just not scored):
- "Too short — not scored. Say the whole sentence." Speak the full sentence.
- "Too quiet — not scored. Move closer to the mic." Raise the mic level or move closer.
- "Too loud — not scored. Lower the mic gain." The recording clips; lower the gain.
- "Could not match this to the sentence — not scored." The take is too garbled or noisy to align. A different sentence
  is usually not caught here: it is scored and shows mostly red and orange cells.
- "No voice found — not scored." Check that the right microphone is selected.
- "Tone model missing — not scored. See docs/running.md." Restore `backend/shadow/scoring/models/tone_v1.*` or retrain.
- "This sentence has no reference timing — not scored." Re-align or edit the sentence in the drawer.
- "Could not align this take — not scored." Record it again.
- "Scoring failed — the take is saved." See the backend log; `make rescore` re-scores once fixed.
