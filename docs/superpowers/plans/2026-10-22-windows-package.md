# Windows Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Windows installer an ordinary person can run: per-user install, a Start-menu icon that sets the app up on
first launch (with a progress page in the browser), then starts the backend, opens the Library in the default browser
and shows a tray icon; releases on GitHub with an update banner; YouTube cookies via a file picker.

**Architecture:** The installer ships a standalone Python 3.12 runtime (for a console-free `pythonw.exe`), `uv.exe`,
`ffmpeg`/`ffprobe`/`deno`, the backend source with its lockfile and the built frontend. A stdlib-only `bootstrap.py`
(run by the shipped `pythonw.exe`) creates the app's virtual environment with uv on first launch while serving a
progress page, prepares the models, updates yt-dlp daily, then hands over to `shadow.launcher` inside the
environment, which runs uvicorn and the tray icon. All user data and model caches live under
`%LOCALAPPDATA%\chinese-shadow-speech`.

**Tech Stack:** Python 3.12 (python-build-standalone), uv, FastAPI/uvicorn, pystray + Pillow, Inno Setup 6, GitHub
Actions (`windows-latest`), React (Settings, Library).

**Spec:** `docs/superpowers/specs/2026-10-22-windows-laptop-design.md` (§2, §5.4–5.7, §6 items 4–6, §7 steps 3–6).
Depends on `2026-10-22-laptop-fit.md` being done (the laptop config sets `int8 = true`, `punctuation = false`).

## Global Constraints

- Windows 10/11 x64, no admin rights, no WSL, no GPU, no developer tools on the user's machine; CPU only.
- No console window, prompt or typed command at any point.
- Backend binds `127.0.0.1` only (never `0.0.0.0`); default port **47231**, fallback to a free port; never 8000
  (dev server) or 8765 (AnkiConnect).
- User data: `%LOCALAPPDATA%\chinese-shadow-speech\data`; model caches (`HF_HOME`, `MODELSCOPE_CACHE`,
  `TORCH_HOME`): `%LOCALAPPDATA%\chinese-shadow-speech\models`; environment: `...\venv`; config:
  `...\config.toml` (device `cpu`, `int8 = true`, `punctuation = false`). Nothing user-owned inside the install
  folder.
- Uninstall asks whether to delete lessons, recordings and models; **default keep**.
- Installer unsigned; per-user (`%LOCALAPPDATA%\Programs\chinese-shadow-speech`).
- yt-dlp self-update at most once a day at startup; a failure never blocks the app.
- Update banner when GitHub's latest release is newer than the running version; no silent self-update.
- The bundled ffmpeg is an **LGPL** build.
- The developer's Linux/WSL GPU setup and `make test` keep working; the lockfile resolves CUDA torch on Linux, CPU torch on
  Windows.
- Never write personal names, email addresses or home-directory paths into files or commit messages.

## Review Focus

1. **A Windows user name with a space and non-ASCII letters** (`C:\Users\Jöhn Doe\AppData\Local\...`): setup,
   SQLite, ffmpeg calls and clip renames all work (Task 2: CI runs the backend tests with a data dir under such a
   path; Task 6 test `test_paths_with_space_and_umlaut`).
2. **Clicking the Start-menu icon again while first-run setup is still running:** no second setup; the browser opens
   the progress page (Task 6, `test_second_start_during_setup_opens_progress`).
3. **No internet or a dropped connection during first run:** a plain message with Retry; Retry resumes, nothing
   half-installed is mistaken for ready (Task 6, `test_failed_setup_is_not_marked_ready`).
4. **Port 47231 already taken by another program:** a free port is used and the browser opens that one; the
   single-instance check finds it via the port file (Task 6, `test_port_fallback_and_port_file`).
5. **Quit from the tray while a lesson builds:** the server stops; on the next start the lesson is marked
   interrupted by the existing `recover_interrupted`, the database is intact (Task 7, `test_quit_stops_server`; manual
   check in Task 9).

---

### Task 1: Settings from a chosen place; laptop config; model preparation

**Files:**
- Create: `backend/shadow/laptop.py`
- Modify: `backend/shadow/config.py` (`load_settings`: `SHADOW_CONFIG` env var when `path` is None)
- Test: `backend/tests/test_laptop.py`, `backend/tests/test_config.py`

**Interfaces:**
- Produces: `laptop_config_text(home: Path) -> str` (TOML: `[models] device = "cpu"`, `int8 = true`,
  `punctuation = false`; `data_dir = "<home>/data"` written with forward slashes); `ensure_laptop_config(home: Path)
  -> Path` (writes it once, never overwrites); `model_env(home: Path) -> dict[str, str]` (`HF_HOME`,
  `MODELSCOPE_CACHE`, `TORCH_HOME` under `<home>/models`); `python -m shadow.laptop prepare` loads every model once
  through `build_deps` (recogniser, aligner, tone embedder, char-CTC; int8 as configured), printing one JSON line per
  step `{"step": str, "done": int, "total": int}` and exiting non-zero with `{"error": str}` on failure.
  `prepare` must also build the stored int8 copies of the aligner and sounds models (`shadow.quant.cached_int8`, under
  `<SHADOW_MODELS_DIR>/int8/`) and download the sherpa punctuation model, so the app never quantises or downloads
  during a take or a lesson build (the cold-cache peaks of building them were never measured).

- [ ] **Step 1: Failing tests** — `test_shadow_config_env_wins(monkeypatch, tmp_path)`;
  `test_laptop_config_is_cpu_int8_unpunctuated(tmp_path)` (parse with `load_settings`: device cpu, int8 True,
  punctuation False, data_dir == home/"data"); `test_ensure_laptop_config_never_overwrites(tmp_path)`;
  `test_model_env_points_under_home(tmp_path)`.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/test_laptop.py tests/test_config.py -q` → FAIL.
- [ ] **Step 3: Implement** as in Interfaces (`prepare` is exercised by Task 9, not unit-tested).
- [ ] **Step 4: Run** `cd backend && uv run pytest -q` → all pass.
- [ ] **Step 5: Commit** `feat(laptop): config location, laptop config, model preparation command`.

### Task 2: CPU torch on Windows; Windows CI

**Files:**
- Modify: `backend/pyproject.toml` (`[tool.uv.sources]`: torch/torchaudio from `pytorch-cu126` with marker
  `sys_platform == 'linux'`, from a new explicit index `pytorch-cpu` (`https://download.pytorch.org/whl/cpu`) with
  marker `sys_platform == 'win32'`; new extra `desktop = ["pystray>=0.19", "pillow>=10"]`), `backend/uv.lock`
- Create: `.github/workflows/ci.yml`

**Interfaces:**
- Produces: a lockfile that resolves on Linux (CUDA 12.6 wheels) and Windows (CPU wheels); a CI workflow with jobs
  `linux` (`make test`) and `windows` (backend non-model tests and frontend tests on `windows-latest`, ffmpeg installed
  on the runner, with `SHADOW_TEST_TMP` pointing at a directory named `Jöhn Doe` so test data dirs contain a space
  and a non-ASCII letter).

- [ ] **Step 1:** Edit sources, run `cd backend && uv lock` and `uv sync --extra dev --extra models` on Linux; check
  `uv run python -c "import torch; print(torch.version.cuda)"` still prints `12.6`.
- [ ] **Step 2:** Make the test fixtures that create data dirs honour `SHADOW_TEST_TMP` (in `tests/conftest.py`,
  `data_dir` under `Path(os.environ["SHADOW_TEST_TMP"])` when set, else `tmp_path`).
- [ ] **Step 3:** Write `ci.yml` (on push and pull_request). Push a branch; open the run.
  Expected: `linux` green; `windows` runs — failures are expected and fixed in Step 4.
- [ ] **Step 4: Fix Windows failures.** Known suspects: renaming or deleting a file that is still open
  (`reenrich._move_clips`, `renumber`, rebuild swaps, attempt cleanup) — close handles first or use `os.replace`;
  paths built with `/` in strings; `trim_heap` must stay a silent no-op. One commit per root cause, each with a test
  that failed on Windows before the fix.
- [ ] **Step 5:** Both jobs green. Commit `build: CPU torch on Windows, desktop extra, CI on Linux and Windows`.

### Task 3: YouTube cookies from Settings

**Files:**
- Modify: `backend/shadow/ingest/youtube.py` (`YtDlpDownloader.__init__(cookies_file: str = "", data_dir: Path |
  None = None)`; cookies path resolved per call: `cookies_file` if set, else `<data_dir>/youtube-cookies.txt` if it
  exists), `backend/shadow/deps.py`, `backend/shadow/api/` (new router `settings.py`), `backend/shadow/main.py`
  (include router), `frontend/src/api/client.ts`, `frontend/src/pages/Settings.tsx`
- Test: `backend/tests/test_settings_api.py`, `backend/tests/test_youtube.py`, `frontend/src/pages/Settings.test.tsx`

**Interfaces:**
- Produces: `GET /settings/youtube-cookies` → `{"present": bool}`; `PUT /settings/youtube-cookies` (multipart field
  `file`) → `{"present": true}`, 400 when the file is not a Netscape cookies file (first non-empty line must be
  `# Netscape HTTP Cookie File` or `# HTTP Cookie File`); `DELETE /settings/youtube-cookies` → 204.
  `api.settings.youtubeCookies.{get, put(file: File), remove}` in `client.ts`.

- [ ] **Step 1: Failing tests** — backend: put/get/delete round trip; non-Netscape file → 400 and nothing stored;
  downloader uses the stored file when `cookies_file` is empty and the configured one when set. Frontend: the YouTube
  section shows "Cookies: none" / "Cookies: added" from `get`, a file picker calls `put`, Remove calls `remove`; the
  old text about editing `config.toml` is gone.
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/test_settings_api.py tests/test_youtube.py -q` and
  `cd frontend && npx vitest run src/pages/Settings.test.tsx` → FAIL.
- [ ] **Step 3: Implement.** Copy in Settings: "Some videos need you to be signed in to YouTube. Export your YouTube
  cookies to a cookies.txt file with a browser extension and add the file here." Use the existing style components
  (`Button`, etc.) as the rest of Settings does. `COOKIES_HINT` in `youtube.py` stays "this video needs a cookies file
  — see Settings".
- [ ] **Step 4: Run** `make test` → passes.
- [ ] **Step 5: Commit** `feat(settings): add YouTube cookies with a file picker`.

### Task 4: Release version and update banner

**Files:**
- Create: `backend/shadow/api/app.py`, `frontend/src/components/UpdateBanner.tsx`
- Modify: `backend/shadow/config.py` (`AppCfg.releases_api: str =
  "https://api.github.com/repos/BeatTheBullets/chinese-shadow-speech/releases/latest"`, `Settings.app`),
  `backend/shadow/main.py`, `frontend/src/api/client.ts`, `frontend/src/pages/Library.tsx`
- Test: `backend/tests/test_app_api.py`, `frontend/src/components/UpdateBanner.test.tsx`

**Interfaces:**
- Produces: `GET /app/update` → `{"current": str, "latest": str | null, "url": str | null, "newer": bool}`. Current
  version from `importlib.metadata.version("shadow")`; latest from the releases API (`tag_name` without a leading
  `v`, `html_url`), fetched at most once per 24 h per process, 5 s timeout; any failure gives `latest: null, newer:
  false`. Versions compared numerically (`major.minor.patch`). `UpdateBanner` renders nothing unless `newer`, else
  "A new version (X) is available — Download" linking to `url` (opens in a new tab), with a dismiss button remembered
  for that version in `localStorage` (try/catch).

- [ ] **Step 1: Failing tests** — backend with the HTTP call monkeypatched: newer, same, older, network error,
  malformed tag; the cache prevents a second fetch within 24 h. Frontend: hidden when not newer; shows version and
  link; dismiss hides it for that version only.
- [ ] **Step 2: Run** them → FAIL.
- [ ] **Step 3: Implement**; mount `<UpdateBanner />` at the top of the Library page.
- [ ] **Step 4: Run** `make test` → passes.
- [ ] **Step 5: Commit** `feat(app): update banner from GitHub releases`.

### Task 5: Launcher inside the environment (server + tray)

**Files:**
- Create: `backend/shadow/launcher.py`
- Test: `backend/tests/test_launcher.py`

**Interfaces:**
- Consumes: `create_app`, `load_settings` (via `SHADOW_CONFIG`), `model_env` (Task 1).
- Produces: `python -m shadow.launcher --port P --home DIR`: runs `uvicorn.Server` for `create_app()` on
  `127.0.0.1:P` in a thread; when `/health` answers, writes `<home>/run/port` (text `P`) and opens
  `http://127.0.0.1:P/` with `webbrowser.open`; shows a pystray icon (tooltip "chinese-shadow-speech", menu **Open**,
  **Quit**); Quit sets `server.should_exit`, waits for the thread, removes the port file and stops the icon.
  Testable core: `ServerHandle(app, port).start() / .wait_ready(timeout) -> bool / .stop()`.

- [ ] **Step 1: Failing tests** — `test_server_handle_starts_answers_and_stops` (a tiny FastAPI app on a free
  port: ready within 10 s, `/health`-like route answers, after `stop()` the port is closed);
  `test_quit_stops_server` (the tray's Quit callback, invoked directly, stops the handle and removes the port file).
  pystray is not imported in tests (the icon is created only in `main()`).
- [ ] **Step 2: Run** `cd backend && uv run pytest tests/test_launcher.py -q` → FAIL.
- [ ] **Step 3: Implement.** Icon image: `packaging/windows/icon.ico` loaded with Pillow (Task 7 adds the file; fall
  back to a plain generated square if missing).
- [ ] **Step 4: Run** `cd backend && uv run pytest -q` → passes.
- [ ] **Step 5: Commit** `feat(launcher): server thread, browser open, tray with Open and Quit`.

### Task 6: First-run bootstrap (stdlib only)

**Files:**
- Create: `packaging/windows/bootstrap.py`, `packaging/windows/progress.html`
- Test: `packaging/windows/test_bootstrap.py` (run with `cd backend && uv run pytest ../packaging/windows -q`)

**Interfaces:**
- Consumes: the installed layout `{app}\python\pythonw.exe`, `{app}\uv.exe`, `{app}\tools\` (ffmpeg, ffprobe,
  deno), `{app}\backend\` (source, `pyproject.toml`, `uv.lock`), `{app}\frontend\dist\`; `shadow.laptop` (Task 1),
  `shadow.launcher` (Task 5).
- Produces: `bootstrap.py` (no third-party imports) with testable functions:
  `home_dir() -> Path` (`%LOCALAPPDATA%\chinese-shadow-speech`); `running_port(home) -> int | None` (port file +
  `/health` answers); `choose_port(preferred=47231) -> int`; `setup_needed(home, lock_hash: str) -> bool` (marker
  `<home>/venv/.ready-<lock_hash>` absent); `run_setup(home, app_dir, report: Callable[[dict], None]) -> bool`
  (holds `<home>/run/setup.lock` for its whole run; steps "Setting up Python" — `uv sync --frozen --no-dev --extra
  models --extra desktop --python {app}\python\python.exe` with `UV_PROJECT_ENVIRONMENT=<home>\venv` and
  `UV_CACHE_DIR=<home>\uv-cache`; "Downloading speech models (about N GB)" and "Preparing models" —
  `<home>\venv\Scripts\python.exe -m shadow.laptop prepare` with `model_env(home)`, relaying its JSON lines; writes the
  marker only after both succeed); `update_ytdlp(home)` (once per day, marker `<home>/run/ytdlp-<date>`, `uv pip
  install -U yt-dlp` into the venv, errors swallowed); `main()`.
  `main()` order: if `running_port` → open browser there, exit. If setup is running (lock held) → open the progress
  page, exit. If `setup_needed` → serve `progress.html` + `GET /status` (JSON of the latest report, or `{"error":
  str}`) + `POST /retry` with `http.server` on `choose_port()`, open the browser, run setup; on success stop the
  progress server. Then `update_ytdlp`, then start `<home>\venv\Scripts\pythonw.exe -m shadow.launcher --port P
  --home <home>` (detached, `CREATE_NO_WINDOW`) with environment: `SHADOW_CONFIG=<home>\config.toml` (from
  `ensure_laptop_config`), `SHADOW_FRONTEND_DIST={app}\frontend\dist`, `model_env(home)`, `PATH` prefixed with
  `{app}\tools`. `progress.html` polls `/status` every second, shows the stage text, a bar, the size estimate and,
  on error, the message with a **Retry** button; when the real app answers on the same port it reloads to `/`.
  Disk check before downloading: at least 8 GB free on the drive of `<home>`, else an error report "Not enough disk
  space: N GB free, about 8 GB needed".

- [ ] **Step 1: Failing tests** (Linux-runnable; subprocesses faked):
  `test_paths_with_space_and_umlaut(tmp_path)` (home under `Jöhn Doe/`: marker, lock and port files work);
  `test_port_fallback_and_port_file()` (preferred port bound by the test → another free port; `running_port` reads
  it back only when `/health` answers); `test_second_start_during_setup_opens_progress(tmp_path)` (lock held → main
  opens the progress URL and does not run setup); `test_failed_setup_is_not_marked_ready(tmp_path)` (failing `uv
  sync` fake → report has `error`, no marker; retry with a passing fake → marker written);
  `test_disk_check_reports_shortfall(tmp_path, monkeypatch)`; `test_ytdlp_update_once_a_day(tmp_path)`.
- [ ] **Step 2: Run** `cd backend && uv run pytest ../packaging/windows -q` → FAIL.
- [ ] **Step 3: Implement** as in Interfaces. Stage texts verbatim: "Setting up Python", "Downloading speech models
  (about N GB)", "Preparing models", "Starting".
- [ ] **Step 4: Run** the tests → pass.
- [ ] **Step 5: Commit** `feat(packaging): first-run bootstrap with progress page`.

### Task 7: Installer and release build

**Files:**
- Create: `packaging/windows/shadow.iss`, `packaging/windows/build.ps1`, `packaging/windows/icon.ico`,
  `packaging/windows/versions.json`, `.github/workflows/release.yml`

**Interfaces:**
- Consumes: everything above.
- Produces: `build.ps1 -Version X.Y.Z` → `dist\chinese-shadow-speech-X.Y.Z-setup.exe`. `versions.json` pins exact
  versions and SHA-256 of: python-build-standalone CPython 3.12 `x86_64-pc-windows-msvc` `install_only`; uv Windows
  zip; an **LGPL** ffmpeg win64 build (includes `ffprobe.exe`); deno Windows zip. `build.ps1` downloads and verifies
  them, runs `npm ci && npm run build` in `frontend`, copies the backend via `git archive HEAD backend`, and runs
  `ISCC.exe`. `release.yml`: on tag `v*`, `windows-latest` installs Inno Setup, runs `build.ps1 -Version
  ${tag without v}`, checks that the tag matches `backend/pyproject.toml`'s version, and attaches the installer to the
  GitHub Release.
  `shadow.iss`: `PrivilegesRequired=lowest`, `DefaultDirName={localappdata}\Programs\chinese-shadow-speech`, Start-menu
  shortcut (optional desktop shortcut task) running `{app}\python\pythonw.exe "{app}\bootstrap.py"` with
  `icon.ico`; `[UninstallDelete]` removes `{localappdata}\chinese-shadow-speech\venv` and `\uv-cache`; a `[Code]`
  uninstall step asks "Also delete your lessons, recordings and downloaded speech models?" (default **No**) and
  removes `{localappdata}\chinese-shadow-speech` only on Yes. Installing over an older version keeps everything under
  `%LOCALAPPDATA%\chinese-shadow-speech`.

- [ ] **Step 1:** Write the files; bump `backend/pyproject.toml` version to `0.2.0`.
- [ ] **Step 2:** Run `release.yml` via `workflow_dispatch` with a test version on a branch (artifact only, no
  release). Expected: an installer artifact of a few hundred MB at most (no models, no venv inside).
- [ ] **Step 3:** Commit `build(windows): Inno Setup installer and release workflow`.

### Task 8: Licence, public repo, first release (the user's steps)

- [ ] **Step 1:** Ask the user to choose the licence (GPL-3.0 suggested: parselmouth is GPL-3). Add `LICENSE`, the
  README licence line, and a `THIRD_PARTY.md` listing bundled components and model licences (ffmpeg LGPL, deno MIT,
  CPython PSF, uv MIT/Apache-2.0; MMS_FA CC-BY-NC-4.0, char-CTC Apache-2.0, tone embedder MIT, Paraformer: FunASR model
  licence). Commit `docs: licence and third-party notices`.
- [ ] **Step 2:** Re-run the privacy scan before going public: no personal names, emails or home paths in any
  revision (`git rev-list --all | xargs git grep -I -i -l -E '<name>|gmail|/home/'` → nothing) and every author is the
  noreply identity. Report to the user.
- [ ] **Step 3:** The user flips the repo to public (GitHub → Settings → Change visibility), then pushes tag
  `v0.2.0`. Expected: the release workflow attaches `chinese-shadow-speech-0.2.0-setup.exe`.

### Task 9: Acceptance

**Files:**
- Create: `docs/windows-acceptance.md`; Modify: `README.MD` (an "Install on Windows" section: download link to the
  latest release, SmartScreen "More info → Run anyway", disk and memory requirements, where data lives, uninstall).

- [ ] **Step 1:** Write `docs/windows-acceptance.md` from spec §6 items 4–6 as a checklist: the CPU budget benchmark
  (`scripts/cpu_budget.py --device cpu --int8 --threads 4 --budget`) on Windows within budget; on the first user's
  laptop: download, SmartScreen, install, first-run progress to the Library, paste a YouTube link, lesson builds, takes
  in Echo and Flow scored, Quit from the tray, quick restart, install a newer build over it and the lessons are still
  there, uninstall keeps data by default; on the GPU machine `make dev` and `make test` still work.
- [ ] **Step 2:** Run the benchmark on Windows (the user's Windows side or the CI runner); record numbers in the
  checklist. Hand the checklist to the user for the laptop run.
  Acceptance also includes one `scripts/cpu_budget.py --cold-int8 --device cpu --int8 --threads 4 --budget` run: the
  int8 copies are built from scratch there, the peak the laptop would see if `prepare` were skipped.
- [ ] **Step 3:** Commit `docs: Windows install and acceptance checklist`.
