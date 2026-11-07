# Windows package acceptance

The installer, first run and memory budget on Windows. Spec: `docs/superpowers/specs/2026-10-22-windows-laptop-design.md`
§6, items 4–6.

## 1. Memory budget on Windows (done on the developer's Windows PC)

Run with the app closed (Quit from the tray icon: closing the browser tab leaves it running). From a dev checkout
(`cd backend && uv sync --frozen --extra dev --extra models`), with the model caches pointed at the installed app's
models (`HF_HOME`, `MODELSCOPE_CACHE`, `TORCH_HOME`, `SHADOW_MODELS_DIR` under `%LOCALAPPDATA%\chinese-shadow-speech\models`)
and `SHADOW_CONFIG` pointing at a config with `[models] device = "cpu"`, `int8 = true`, `punctuation = "sherpa"`.
To measure what a laptop under 12 GB of RAM gets, that config also sets `asr_int8_below_ram_gb = 64` so the
recogniser is 8-bit on a bigger machine too.

    python scripts/cpu_budget.py --clip clip300.wav --device cpu --int8 --threads 4 --budget
    python scripts/cpu_budget.py --clip clip300.wav --device cpu --int8 --threads 4 --budget --cold-int8

Budgets: startup 3000 MB, build 3500 MB, practice 3100 MB, build+practice 3500 MB.

Results on 2026-11-07 (Windows 11, Ryzen 5 3600, 4 threads, a 5-minute clip, the 8-bit recogniser forced):

- [x] Warm run (int8 copies already stored, as after the first-run `prepare`): startup 425 MB, build 2479 MB,
  practice 2733 MB, build+practice 2902 MB. All within budget. Takes 0.4–8.9 s, most 3.5–5.5 s.
  Before the app's own int8 layers (commit "weight-only int8 Linear"), the same run passed 3755 MB in practice:
  the Windows PyTorch wheel has only the oneDNN quantised engine, which keeps every int8 weight twice.
- [x] Cold run (`--cold-int8`: the int8 copies and the punctuation model are built during the run): stopped at the
  safety cap in practice, at least 3806 MB, because the sounds model's int8 copy is built during the first take with
  the other models loaded. The installed app never takes this path: setup runs `prepare`, which builds the copies
  first, and runs again for every new app version.
- [x] `prepare` with the int8 copies built from scratch (what the first start and every update run, before the app
  starts): peak 3.3 GB, one model at a time.

Quality of the app's int8 layers against fp32 (Linux, `scripts/int8_check.py`, `split_gate.py --int8`,
`tests/test_sounds_real.py`, `tone_model.py --int8-aligner`), all PASS: alignment +0.0 ms; words-check agreement
98.4 % over 319 takes; transcript CER 0.95 %; sounds caught 82.8 %, false alarms 3.9 %; tone within 0.05 points;
sentence splitting end recall 0.794, F1 0.753 (fp32 0.792, 0.756).

## 2. Installer and first run (done on the developer's Windows PC, 2026-11-06)

Windows 11, AMD Ryzen 5 3600 (6 cores), 16 GB RAM, so the recogniser stayed fp32.

- [x] `packaging\windows\build.ps1` builds `dist\chinese-shadow-speech-0.2.0-setup.exe` (153 MB).
- [x] Silent per-user install (`/VERYSILENT`), no administrator prompt; Start-menu shortcut created.
- [x] First start from the shortcut: progress page, then ready after about 10 minutes (Python environment and 4.7 GB
  of models).
- [x] YouTube lesson (a 3-minute HSK story): built in about 2 minutes, 57 sentences, punctuation correct.
- [x] Echo takes scored: first take 6.7 s (models load), then 3.5–4.8 s each. Server memory 3.9 GB with all five
  models loaded (fp32 recogniser).
- [x] A newer build installed over the running app: the app was stopped (other programs' Python processes untouched),
  the lesson was kept, and the app was ready 13 s after starting it from the shortcut (measured before setup reran on
  every new version).
- [x] Re-checked 2026-11-07 with the final build installed over the previous one: the progress page showed "Updating
  the app", then "Checking speech models" (no download), and the app was ready 77 s after the shortcut. The int8
  copies were in the new format; the lesson was kept; the same take scored 0.977 (0.975 before).
- [x] Start without internet (all traffic sent to a dead proxy, models already downloaded): ready in 8 s, takes scored
  (first take 14 s while the models load, then about 5 s). Before the offline fix, three of the five models failed to
  load without internet.

## 3. On the first user's laptop

- [ ] Download the installer from the release page. SmartScreen: **More info → Run anyway**.
- [ ] Install. The first start shows the progress page and ends on the Library. Note the time: ____ min.
- [ ] Paste a YouTube link. The lesson builds. Note the time for a ~3-minute video: ____ min.
- [ ] Record takes in Echo and in Flow; both are scored. Note the seconds per Echo take after the first: ____ s.
- [ ] The laptop stays usable while the app runs (browser, music). Task Manager → the app's `pythonw.exe` memory
  after a few takes: ____ MB.
- [ ] **Quit** from the tray icon. Start again from the Start menu: the Library opens within about 30 s.
- [ ] Install a newer build over it: the first start shows "Updating Chinese Shadow Speech" (no 4 GB download) and
  ends on the Library. Note the time: ____ min. The lessons and takes are still there.
- [ ] Uninstall (Settings → Apps): it asks whether to delete the data, the default is No, and
  `%LOCALAPPDATA%\chinese-shadow-speech\data` is still there after answering No.

## 4. Development machine

- [ ] On the GPU machine (WSL2), `make dev` and `make test` still work, and `/health` reports `"device": "cuda"`.
