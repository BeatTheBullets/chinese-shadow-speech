# Running

## Dev (WSL2, GPU)
    cd backend && uv sync --extra dev --extra models      # pulls torch from the PyTorch cu126 index
    cd .. && make dev

The GPU driver must support CUDA 12.6 (Windows NVIDIA driver >= 560).
First ingest downloads Paraformer-zh (~1 GB, ModelScope) and the MMS_FA aligner (~1.2 GB, torchaudio).
Before the first real ingest, smoke-test Paraformer and the aligners: `cd backend && uv run pytest -m models`.
Verify the GPU is seen: `curl -s localhost:8000/health` -> `"device": "cuda"`.

## CPU only
Set `[models] device = "cpu"` in config.toml; the aligner is MMS_FA on every device (`aligner = "qwen3_fa"` selects Qwen3 explicitly).
On a laptop with 8 GB of RAM also set these in `[models]`:
- `int8 = true`: the recogniser, aligner and sounds model run as 8-bit models (about half the RAM, slower per take). The
  aligner and the sounds model are quantised once and stored in `int8/` under the app's models folder (`SHADOW_MODELS_DIR`),
  so later loads read int8 weights only; the recogniser is quantised at each load.
- `int8_skip = []`: models kept fp32 even with `int8 = true`, from `"asr"`, `"aligner"`, `"sounds"` (more RAM, closest to the GPU results).
- `threads = 0`: CPU threads for the models; 0 is the physical cores minus one. 4 was used for the memory measurements.
- `punctuation = "sherpa"`: sentence ends come from the small sherpa-onnx model (about 0.18 GB, downloaded on first use);
  `"pauses"` cuts sentences at pauses instead.

## Docker
    cd frontend && npm run build        # produces frontend/dist, which the image copies
    docker compose up --build

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
Paraformer (the ingest recogniser, which also checks each take's words) loads in the background at start-up the same way.
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
(`min_rms_dbfs`, `min_align_conf`, `min_text_similarity`, `words_ok_at`).

To check that each sentence's clip says its text, run `cd backend && ~/.local/bin/uv run python scripts/clipcheck.py
--lesson N` (or `--all` for every ready lesson). Read only: the recogniser hears each clip and the words check
(toneless pinyin similarity) compares it with the sentence; it prints the sentences below 0.8 and per lesson n, how
many match and the mean. A lesson whose text runs ahead of its audio (lessons transcribed before the FunASR
`sentence_info` fix of 2026-10-12, one character more after each pause) scores far lower: **⟲ Rebuild text** on its
library tile transcribes it again and rebuilds its sentences and clips; your takes move to the sentence at the same
time and are scored again (difficulty flags and Anki notes move with them).

Voice profile: tones are judged against your own pitch range, which is learned from your most recent minute or so of voiced speech and keeps adapting as you practise.
Settings -> Voice profile shows it; **Reset voice profile** empties it (for a new mic or after a bad take) and the next
takes rebuild it.

Gate warnings (the take is always saved, it is just not scored):
- "Too short — not scored. Say the whole sentence." Speak the full sentence.
- "Too quiet — not scored. Move closer to the mic." Raise the mic level or move closer.
- "Too loud — not scored. Lower the mic gain." The recording clips; lower the gain.
- "Heard different words — not scored. Heard: …" The speech recogniser (the Paraformer model ingest uses) heard
  other words than the sentence shown (toneless pinyin similarity below `min_text_similarity`, 0.25). Say the sentence
  shown. A wrong tone alone does not trigger this; a sentence sharing most of its words with the one shown can pass.
  While a video is being imported the recogniser is busy: a take then waits at most 2 s and is tone-scored without
  the check.
- "Could not match this to the sentence — not scored." The take is too garbled or noisy to align.
- "No voice found — not scored." Check that the right microphone is selected.
- "Tone model missing — not scored. See docs/running.md." Restore `backend/shadow/scoring/models/tone_v1.*` or retrain.
- "This sentence has no reference timing — not scored." Re-align or edit the sentence in the drawer.
- "Could not align this take — not scored." Record it again.
- "Scoring failed — the take is saved." See the backend log; `make rescore` re-scores once fixed.

Notice on a scored take (the score stands):
- "Some words sounded different — heard: …" The similarity was between `min_text_similarity` (0.25) and
  `words_ok_at` (0.55): a few words were misheard or mispronounced. Compare what was heard with the sentence.
