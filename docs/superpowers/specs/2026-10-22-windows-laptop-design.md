# Windows laptop version — design

Date: 2026-10-22. Status: agreed in conversation with the user; written for the builder.

## 1. Intent

Today the app runs only on the user's machine: a WSL2 Linux backend with an NVIDIA GPU (8 GB VRAM), a browser on
Windows, a dozen terminal commands to start it. The goal is a version an ordinary person can install and use on an
ordinary Windows laptop. The first such person is a non-technical first user, on their own average laptop (8 GB of
RAM, integrated graphics). The app is aimed at **average laptops**, not just that one.

What they should experience: download one installer, click through Windows' SmartScreen warning once ("More info →
Run anyway"), run it, and from then on click a Start-menu icon and land in the **Library** in their browser, where they
paste a YouTube link and practise as the developer does.

This is the first of four projects; the others (Bilibili links, podcast feeds, a Microsoft Store edition) come later
and are out of scope here (§9 notes what this design must not make harder for them).

## 2. Goals, non-goals, anti-goals

**Goals**
- Runs natively on Windows 10/11 x64, with no WSL, no GPU and no developer tools on the user's machine.
- Fits an **average laptop: 8 GB RAM, no NVIDIA GPU, 4 cores** (§3).
- One-click start: Start-menu icon → backend starts → Library opens in the default browser; a tray icon shows it is
  running and offers Open and Quit.
- First launch sets itself up (Python, packages, models) behind a progress page in the browser; later launches start
  in seconds.
- Their lessons and recordings survive app updates and reinstalls.
- the user's own setup (WSL2, CUDA, `make dev`, `make test`) keeps working.

**Non-goals (this project)**
- Microsoft Store / MSIX, code signing, Bilibili, podcast feeds, macOS/Linux installers, mobile.
- Anki on their machine (AnkiConnect stays optional and unconfigured; nothing may break without it).
- An NVIDIA/CUDA build for Windows. CPU only.
- A native app window (pywebview/Tauri/Electron). Their normal browser is the UI.

**Anti-goals (failure even if it "works")**
- Sentence splitting that is worse than today's (the user: "we need to be sure the sentence splitting doesn't
  suffer").
- Tone, sounds or words-check results that silently get worse because models were shrunk.
- A console window, a Python prompt, or any step that asks them to type a command.
- Losing their recordings on update or reinstall.

## 3. The target machine and the measured problem

Measured 2026-10-22 on the user's WSL2 (7.7 GB RAM — a fair stand-in for an 8 GB laptop), CPU only
(`CUDA_VISIBLE_DEVICES=""`), 4 threads. Every RSS figure includes ~0.48 GB of Python + PyTorch base.

| Model (current, fp32 on CPU) | RSS after load | Time |
|---|---|---|
| Paraformer-large + fsmn-vad, no punctuation model | 3.3 GB | 5-min clip: 21 s · one ~4 s take: 0.8 s |
| + `ct-punc` (punc_ct-transformer_cn-en-common-vocab471067-large) | OOM-killed above ~5 GB | — |
| MMS_FA aligner | 2.2 GB (peak 3.0) | one take: 1.0 s · 60 sentence windows: 74 s |
| char-CTC sounds model (wbbbbb/wav2vec2-large-chinese-zh-cn) | 1.0 GB (peak 2.4) | ~1.8 s per take |
| tone embedder (TencentGameMate/chinese-wav2vec2-base) | 0.8 GB | ~0.6 s per call |

The full app (all models resident, as today) was OOM-killed during startup + ingest at 5.5 GB RSS. **Memory, not
speed, is the blocker.** Speed is acceptable: on this machine ~2 min to build a 5-min lesson and ~5 s to score a take;
a laptop CPU is probably 1.5–2× slower (estimate, not measured).

**Memory budget (my call):** an 8 GB Windows laptop with a browser open leaves roughly 3.5 GB. The backend's peak
RSS must stay **≤ 3.1 GB while practising** and **≤ 3.5 GB while building a lesson**, including transient peaks
during model loading. (Practising budget raised from 3.0 to 3.1 GB: measured 3.04-3.10 GB, user decision 2026-10-23.)

The measurement scripts used for this live in the session scratchpad; the builder turns them into a committed script
(`backend/scripts/cpu_budget.py` or similar) that runs the real app on a scratch data dir: build a lesson from a
5-minute clip, then score 8 takes, printing time and peak RSS per phase.

Also found: at startup, the char-CTC warm-up can fail with `ImportError: cannot import name 'Wav2Vec2CTCTokenizer'`
because the embedder's and char-CTC's warm-up threads import `transformers` concurrently. The app recovers (the
next take loads it), but it is a real bug and must be fixed (e.g. serialise warm-ups, or import `transformers` once
before starting the threads).

## 4. Decisions the user made

1. **Load models per phase** instead of keeping all of them resident.
2. **Split sentences on pauses**, dropping the punctuation model. Unpunctuated text is acceptable for lessons
   without Chinese subtitles — **provided sentence splitting does not get worse** (§5.2 gate).
3. **Shrink the big models to 8-bit**, with tone, sounds and the words check re-validated (§5.3).
4. **Keep both the MMS aligner and the char-CTC sounds model.** (Checked: the sounds detector's fused score uses
   MMS letter GOP as model A and char-CTC as model B; its thresholds — 79 % caught at 3.9 % false alarms on the user's
   check set — are calibrated on the pair. Merging them is off the table.)
5. Direct download first; the Store comes later as a separate project.
6. Unsigned installer is fine for the first user (SmartScreen "Run anyway" once).

## 5. Design

### 5.1 Memory: per-phase loading

Two phases with different model sets:

- **Lesson building** (YouTube/upload ingest, "Rebuild text"): recogniser (Paraformer + VAD) and aligner.
- **Practice** (scoring takes): aligner, tone embedder, char-CTC sounds model, and the recogniser for the words
  check.

With `ct-punc` gone (§5.2), the building set is a subset of the practice set, so per-phase loading saves less than
first thought: its job is to **not load the practice-only models (tone embedder, char-CTC) until the first take
arrives** (today they are warmed up at startup), so a session that only builds lessons stays small. Most of the saving
has to come from 8-bit (§5.3).

Practising while another lesson builds stays possible, as today: `ensure_idle` only blocks takes and edits on the
lesson being built, and a take that finds the recogniser busy skips the words check after `HEAR_WAIT_S` (2 s)
(my call: keep this behaviour; no UX change). The budget therefore has a **worst case: building a lesson while
scoring takes, ≤ 3.5 GB peak**; practice alone ≤ 3.1 GB; both include the moment of loading. Long videos (up to
`max_minutes` = 90) must not push the building peak over budget through activation memory — transcribe in bounded
chunks if needed.

Rules:
- Windows has no `malloc_trim` (`memory.trim_heap` is already a no-op there). Whether freed memory returns to the OS
  on Windows must be measured on Windows, not assumed.
- On the user's GPU machine behaviour may stay as today (all resident on the GPU); per-phase unloading may be limited to
  `device == "cpu"`. Builder's choice, as long as the user's setup keeps working.

If, after 8-bit (§5.3), the recogniser alone still breaks the practice budget, the builder may give the words check a
smaller recogniser, provided the words-check validation in §5.3 still passes. Loading the recogniser per take is not
acceptable (7 s load).

### 5.2 Sentence splitting on pauses

> **Outcome (user decision 2026-10-23):** the splitting gate rejected pause splitting. Punctuation now comes from the small int8 sherpa-onnx model; the text below is the design as first written.

**What changes.** The `ct-punc` punctuation model is dropped. ASR text is no longer punctuated. Sentences are cut
from the recogniser's per-character timestamps by pause length, with length limits and word boundaries. Lessons
whose text comes from real Chinese subtitles keep their human punctuation and their current splitting (subtitle text
already carries 。！？ and the existing `rectify_transcript` path handles it). One code path on every device: the user's
machine also drops `ct-punc` (my call — one behaviour to test and maintain).

**A first algorithm** (from a simulation on the user's 4 lessons, `jieba` for word boundaries):
1. Cut at every gap ≥ 0.5 s between consecutive characters, except inside a `jieba` word.
2. While a piece is longer than 25 characters, cut it at its largest gap ≥ 0.25 s (not inside a word, leaving ≥ 4
   characters on each side).
3. While a piece is shorter than 4 characters, merge it across the smaller of its two neighbouring gaps.

On the 4 existing lessons (all slow HSK1 stories, ASR + `ct-punc`), against today's punctuation splits: precision
0.87, recall 0.79, 6 of 63 sentence ends missed, pieces 4–23 characters (median 6), none over 25. Several
disagreements look like improvements (it separates a spoken title from the first sentence). The thresholds are a
starting point; the builder tunes them.

**Go/no-go gate (must pass before `ct-punc` is removed).** The 4 lessons are the easy case: slow speech with long
pauses. The gate needs natural-speed speech:
- Reference set: at least 4 natural-speed Mandarin videos (≥ 30 minutes in total; e.g. Mandarin Corner interviews,
  native vlogs) **that have real Chinese subtitles**, plus the user's 4 existing lessons. The subtitles' human sentence
  breaks (。！？ and ，) are the reference boundaries; character times come from the recogniser as today.
- Compare pause splitting with today's `ct-punc` splitting against that reference (boundary precision/recall at the
  character level, sentence ends missed, pieces > 25 characters, pieces < 4 characters, cuts inside a word).
- **Pass:** pause splitting is at least as good as `ct-punc` splitting on recall of sentence ends and on F1 over all
  boundaries, with no piece over 30 characters. the user looks at a printed sample of both splittings for two of the
  natural-speed videos before the switch.
- **Fail:** keep punctuation, but from a **small 8-bit punctuation model** that fits the ingest budget (e.g. an
  int8 ONNX CT-Transformer as shipped by sherpa-onnx — its size and quality to be measured), and split as today.
  the user decides between the options on the numbers.

The gate runs on the user's GPU machine; it only needs the recogniser, `ct-punc` and the subtitle-alignment path that
already exists.

### 5.3 Memory: 8-bit models on the CPU

> **Outcome (user decision 2026-10-23):** the recogniser runs int8 only when the machine has less than 12 GB RAM (`asr_int8_below_ram_gb`), fp32 above, because int8 missed the words check (93.9 %) and CER (3.35 %) marks. The sounds model stays int8 on the CPU everywhere: accepted at 5.3 % false alarms with 86 % of slips caught.
>
> **Later (2026-11):** the method moved from PyTorch dynamic quantisation to the app's own weight-only `Int8Linear`
> (`backend/shadow/quant.py`), because the Windows torch wheel's oneDNN engine keeps every int8 weight twice. Those
> numbers were measured with the old method; with `Int8Linear` the int8 recogniser agrees with fp32 on 98.4 % of
> words checks at 0.95 % CER (`docs/windows-acceptance.md`). The 12 GB rule was kept.

- Quantise to int8 **on the CPU path only**: the recogniser (Paraformer), the MMS aligner and the char-CTC sounds
  model. The tone embedder (wav2vec2-base, 0.35 GB) stays fp32 (my call: it is small, and the tone classifier was
  trained on its fp32 layer-6 features).
- Method is the builder's choice (PyTorch dynamic quantisation of `Linear` layers is the cheapest first try; ONNX
  Runtime int8 is the alternative). Whatever the method, the **load-time peak** counts against the budget: if
  quantising at load means first holding the fp32 model, quantise once (first run) and store the int8 weights, then
  load those.
- **Validation, all on the CPU int8 build, compared with today's fp32 results (thresholds are my call):**
  - *Tone:* the held-out evaluation in `scripts/tone_model.py` (native and pitch-altered accuracy, false-red rate)
    with the aligner swapped for its int8 version — accuracy within 1 point of fp32, false-red within 1 point.
  - *Sounds:* the Phase 3a check set (`.superpowers/sdd/p3a-spike/eval_check.py`, the user's recorded pairs) at the
    calibrated `fused_threshold` — caught within 3 points of 79 %, false alarms ≤ 5 %. If int8 shifts the score
    distributions, the z-normalisers in `[sounds]` may be recalibrated for the CPU build (as a separate CPU profile, not
    overwriting the user's).
  - *Words check:* on the user's stored takes, the words-check verdict (clean / some words different / different words)
    agrees with fp32 on ≥ 95 % of takes.
  - *Alignment:* mean first-character onset error (the `aligncheck` metric) on lesson 1 within 10 ms of fp32.
  - *Lesson building with the int8 recogniser* (my call — it produces both the lesson text and the timestamps pause
    splitting cuts on): on the §5.2 gate set, character error rate of int8 vs fp32 transcripts ≤ 2 %, and the §5.2
    gate rerun with int8 timestamps on the CPU must still pass. This runs in step 1 of the work order, together with
    the gate.
- If one model fails, that model stays fp32 and the budget is re-checked; if the budget then breaks, stop and bring
  the numbers to the user.

### 5.4 Windows-native backend

Known work, not exhaustive:
- **External tools:** `ffmpeg`, `ffprobe` and `deno` are bundled in the install folder and found by path, not
  assumed on `PATH` (`audio.py` calls `ffmpeg`/`ffprobe` by name; `youtube.py` checks `shutil.which("deno")`).
- **PyTorch source:** `pyproject.toml` pins torch/torchaudio to the `pytorch-cu126` index. The Windows install must
  get CPU wheels while the user's Linux keeps cu126 (e.g. uv sources with platform markers). The lockfile must cover
  both.
- **File handling:** Windows cannot rename or delete a file another handle has open; clip renames
  (`reenrich._move_clips`, `renumber`, rebuild swaps) and attempt cleanup must be checked on Windows. Paths may contain
  spaces and non-ASCII characters (user names).
- **Data location (my call):** all user data (`shadow.db`, lessons, attempts, cache) under
  `%LOCALAPPDATA%\chinese-shadow-speech\data`, and the model caches (`HF_HOME`, `MODELSCOPE_CACHE`, `TORCH_HOME`) under
  `%LOCALAPPDATA%\chinese-shadow-speech\models`. Not inside the install folder, so updates and reinstalls keep them.
  `config.toml` for the laptop build is generated there on first run (device `cpu`).
- **Heavy jobs on a laptop:** cap torch threads (e.g. physical cores − 1) so the browser stays responsive.
- The startup race (§3) is fixed.
- The existing test suite stays green on Linux; a Windows CI job (GitHub Actions `windows-latest`) runs the
  non-model backend tests and the frontend tests.

### 5.5 Launcher, tray and first run

- A **launcher** started by the Start-menu shortcut, with no console window (e.g. `pythonw` or a small native stub —
  builder's choice). It:
  - starts the backend on `127.0.0.1` (never `0.0.0.0`) on a fixed default port with fallback if taken — not 8000
    (the user's dev server) and not 8765 (AnkiConnect);
  - opens the default browser at the Library once the server answers;
  - shows a tray icon with **Open** and **Quit** (Quit stops the backend cleanly);
  - is single-instance: clicking the icon again just opens the browser.
- **The browser is the UI.** The microphone works because `http://127.0.0.1` is a secure context. Only `127.0.0.1` /
  `localhost`, never a LAN address.
- **First run** (my call on mechanism): the installer ships `uv.exe`, the app source, the built frontend, the
  lockfile, `ffmpeg`, `ffprobe` and `deno`. On first launch, uv installs Python 3.12 and the locked packages (CPU
  PyTorch), then the app downloads the models (and stores the int8 versions, §5.3). They see this as a **progress
  page in the browser** from the first click, with plain stages ("Setting up Python", "Downloading speech models
  (about N GB)", "Preparing models"), an honest size/time estimate, and a clear message plus retry on failure (no
  internet, disk full). The progress page cannot depend on the full environment existing yet; it is served by
  something that runs before `uv sync` finishes (e.g. a stdlib-only launcher page).
- Disk space is checked before downloading; the requirement is stated on the download page.

### 5.6 Installer

- **Inno Setup**, unsigned, **per-user install** (no admin prompt), into `%LOCALAPPDATA%\Programs\...`.
- Start-menu shortcut; optional desktop shortcut.
- Uninstall removes the program; it **asks** whether to also delete lessons, recordings and models (default: keep).
- Installing a newer version over an older one keeps data and models.
- The installer is built reproducibly from the repo (GitHub Actions on `windows-latest`, or a documented local build
  on Windows).

### 5.7 Releases and updates

- **Where downloads live:** the repo becomes public and installers are attached to **GitHub Releases** (the user's
  choice). Before the first release a licence must be chosen (GPL-3.0 is the natural fit: parselmouth is GPL-3) and
  the repo made public; the bundled `ffmpeg` must be a build whose licence the release can meet (e.g. LGPL). Nothing
  personal goes into the repo (names, emails, home paths); commits use the GitHub noreply identity.

- **yt-dlp** updates itself (YouTube breaks it often): at most once a day, at startup, upgrade the `yt-dlp` package
  inside the app's environment; a failed upgrade never blocks the app.
- **The app** checks for a newer release at startup and shows a small banner in the Library ("A new version is
  available — download"). They install it by running the new installer. No silent self-update. Releases get a
  version scheme (today `pyproject.toml` says 0.1.0 and there are no releases).
- The banner uses the new style components (the `style` branch has merged into main).
- **YouTube sign-in checks** (my call): when yt-dlp hits a bot or age check, they see a plain message saying the video
  needs a signed-in YouTube session, and Settings gets a file picker for a `cookies.txt` (no typing, no editing
  `config.toml`). Reading cookies straight from the browser is not used (unreliable on Windows while the browser is
  open). From a home connection these checks are rarer than from servers.

## 6. Acceptance

1. **Splitting gate** passed (§5.2), or the user has chosen the fallback.
2. **Validation** passed (§5.3) for every int8 model, or the user has accepted the exceptions.
3. **Budget** (§3) met on the 8 GB proxy (WSL2, CPU only, 4 threads) with the committed benchmark script: build a
   5-minute lesson, then score 8 takes, then score takes on that lesson while a second lesson builds; no OOM, peaks
   within budget. Report time per lesson and per take.
4. **Windows:** the same benchmark on a Windows machine (the user's Windows side or a CI runner) within budget.
5. **The first user's laptop:** install from the downloaded installer, first-run setup completes, Library opens, they paste a
   YouTube link, the lesson builds, they record takes in Echo and Flow and sees scores; quit from the tray; restart
   is quick; install a newer build over it and their lessons are still there.
6. the user's WSL/GPU setup still works and `make test` passes.

## 7. Order of work

1. Splitting gate and int8 validation first — they decide the model plan and can fail.
2. Per-phase loading, the startup race fix, the benchmark script.
3. Windows-native backend (paths, tools, PyTorch source, file handling, data location), Windows CI.
4. Launcher, tray, first-run progress page.
5. Installer, update check, yt-dlp self-update.
6. Acceptance on the first user's laptop.

Work happens in its own git worktree/branch. Frontend pieces: the first-run progress page (served outside the React
app), the update banner and the cookies-file picker in Settings.

## 8. Left to the builder

- Quantisation method and tooling; whether per-phase unloading also applies on the GPU.
- Launcher implementation (Python + pystray, or a native stub), port number, tray icon.
- How the first-run progress page is served before the environment exists.
- The exact splitting thresholds, within the gate.
- Thread caps, model-download mirrors and retries.
- Whether the benchmark becomes a pytest `models`-marked test or a script.

## 9. Context for later projects (not built here)

- **Bilibili links** via yt-dlp (needs the user's login cookies; same legal grey zone as YouTube).
- **Podcast RSS feeds** — the source that is safe for the Store.
- **Microsoft Store**: MSIX (Microsoft signs it free), private audience, YouTube included; if rejected or pulled,
  resubmit without YouTube/Bilibili and keep the full version as direct download. The Store build must bundle Python
  and packages (no `uv sync` at first run: Store policy 10.2.2), keep user data outside the package's AppData (deleted
  on uninstall), and must not point users to the outside download (policy 10.1.5). The data-location and model-cache
  choices in §5.4 should not make this harder.
