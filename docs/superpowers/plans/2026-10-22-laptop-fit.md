# Laptop Fit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the backend fit an average laptop (8 GB RAM, CPU only): pause-based sentence splitting instead of the
punctuation model, 8-bit recogniser/aligner/sounds models on the CPU, lazy loading of practice-only models, the
startup race fixed, and a committed memory benchmark that proves the budget.

**Architecture:** Pause splitting lives where the transcript is built (`transcript_from_funasr`), so the rest of the
pipeline (rectify → align → enrich) is unchanged. 8-bit is a load-time option of each model class, on only when the
device is the CPU. Two go/no-go measurements (the splitting gate and the int8 validation) run before defaults change.

**Tech Stack:** Python 3.12, PyTorch 2.11 dynamic quantisation, FunASR Paraformer, torchaudio MMS_FA, transformers
wav2vec2, jieba, pytest.

> **Later change:** the int8 layers no longer use PyTorch's dynamic quantisation (`quantize_dynamic`, qint8). The app
> has its own weight-only `Int8Linear` (`backend/shadow/quant.py`, `QUANT_FORMAT = 2`): the Windows torch wheel has only
> the oneDNN quantised engine, which keeps every int8 weight twice. `quantize_linear` keeps its name and now swaps in
> `Int8Linear`; the Task text below (e.g. `torch.ao.nn.quantized.dynamic.Linear`) is the plan as first written.

**Spec:** `docs/superpowers/specs/2026-10-22-windows-laptop-design.md` (§3, §4, §5.1–5.3, §6 items 1–3, §7 steps 1–2).
The Windows packaging (§5.4–5.7) is the separate plan `2026-10-22-windows-package.md`.

## Global Constraints

- Memory budget, backend peak RSS including the moment of loading: **≤ 3.1 GB while practising (measured 3.04-3.10 GB; user decision 2026-10-23); ≤ 3.5 GB while
  building a lesson, including building while scoring takes**.
- Proxy machine for measurements: WSL2 with 7.7 GB RAM, `CUDA_VISIBLE_DEVICES=""`, 4 torch threads asked for (the budget runs actually used 5, cores - 1: see the Ledger).
- The MMS aligner and the char-CTC sounds model both stay. The tone embedder stays fp32.
- int8 only when the resolved device is `cpu`; the GPU path behaves as today.
- Pause splitting starting values: cut at gaps ≥ **0.5 s**, split long pieces at gaps ≥ **0.25 s**, pieces of
  **4–25** characters, never cut inside a `jieba` word.
- Splitting gate pass: pause splitting ≥ `ct-punc` splitting on **sentence-end recall** and on **F1 over all
  boundaries**, **no piece over 30 characters**, and the user has looked at printed samples for two natural-speed
  videos.
- int8 pass marks: tone accuracy within **1 point** of fp32 (native and altered), false-red within **1 point**;
  sounds caught within **3 points of 79 %** (≥ 76 %) with false alarms **≤ 5 %**; words-check verdict agreement
  **≥ 95 %**; alignment mean onset error within **10 ms**; int8 vs fp32 transcript CER **≤ 2 %** and the gate rerun
  with int8 timestamps passes.
- Tests never need a GPU, network or model download; anything that does is marked `@pytest.mark.models`.
- Never write personal names, email addresses or home-directory paths into files or commit messages; say "the user".

## Review Focus

1. **Recogniser output whose character count disagrees with its timestamps (Latin words, digits) with punctuation
   off:** the `sentence_info` fallback gives interpolated times with no gaps; pause splitting must still return
   pieces of ≤ 25 characters cut at word boundaries, not one giant sentence (Task 3, test
   `test_no_gaps_still_splits_long_text_at_word_boundaries`).
2. **Fast speech with no gap ≥ 0.25 s inside a 40-character run:** the piece is still cut at a word boundary
   (largest gap, ties nearest the middle) rather than left at 40 characters (Task 3, same test).
3. **A transcript shorter than the minimum (1–3 characters) or a single word:** one piece, no endless merge loop
   (Task 3, `test_short_transcript_is_one_piece`).
4. **The first take on a CPU machine arrives while the recogniser warms up or a lesson builds:** embedder and char-CTC
   load once under their locks, not twice, and the transformers import happens once (Task 2,
   `test_wav2vec2_classes_import_once_across_threads`).
5. **`int8 = true` on a CUDA machine:** ignored, models stay fp32 on the GPU (Task 5,
   `test_int8_only_on_cpu`).

---

### Task 1: CPU memory benchmark

**Files:**
- Create: `backend/scripts/cpu_budget.py`
- Modify: `backend/pyproject.toml` (add `psutil>=5.9` to the `dev` extra), `backend/uv.lock`

**Interfaces:**
- Produces: `uv run python scripts/cpu_budget.py --clip PATH [--device cpu] [--int8] [--threads 4] [--budget]
  [--phases startup,build,practice,build+practice]` (default: all four),
  printing one JSON line `{"phases": [{"name", "seconds", "peak_mb"}], "take_seconds": [...]}`; with `--budget` it
  exits 1 when a phase peak exceeds its budget (`startup`: 3000 MB, `practice`: 3100 MB; `build`, `build+practice`: 3500 MB).

- [ ] **Step 1: Add `psutil` to the dev extra and lock**

Run: `cd backend && uv add --optional dev "psutil>=5.9" && uv sync --extra dev --extra models`
Expected: lockfile updated; `uv run python -c "import psutil"` succeeds.

- [ ] **Step 2: Write `scripts/cpu_budget.py`**

Runs the real app (`create_app(settings, deps=build_deps(settings))` inside `fastapi.testclient.TestClient`) on a
fresh temporary data dir (`tempfile.mkdtemp()`), never the user's data. A background thread samples
`psutil.Process().memory_info().rss` every 0.1 s into the current phase's peak. Phases, in order:
`startup` (until the app serves and `/health` answers), `build` (POST `/lessons` with `--clip`, poll
`/jobs/{id}` until done), `practice` (8 takes: POST `/segments/{id}/attempts` with the lesson's own clip WAVs as
the take audio), `build+practice` (POST the clip again as a second lesson and, while that job runs, score 8 more
takes on the first lesson). `--device`/`--int8`/`--threads` set `settings.models.device`, `settings.models.int8`
(Task 5; ignore if absent) and `torch.set_num_threads`. Module docstring: how to make a 5-minute 16 kHz mono clip
from any lesson's `source.wav` with ffmpeg, and to run with `CUDA_VISIBLE_DEVICES=""`.

- [ ] **Step 3: Record the baseline**

Run: `cd backend && CUDA_VISIBLE_DEVICES="" uv run python scripts/cpu_budget.py --clip <5-min clip> --device cpu --threads 4`
Expected: today's code OOM-kills (exit 137) or prints peaks far over budget. Record the outcome in the Ledger below.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/cpu_budget.py backend/pyproject.toml backend/uv.lock docs/superpowers/plans/2026-10-22-laptop-fit.md
git commit -m "feat(scripts): CPU memory budget benchmark (startup, build, practice, build+practice)"
```

### Task 2: One transformers import; sequential warm-ups; practice models lazy on the CPU

**Files:**
- Create: `backend/shadow/hf.py`
- Modify: `backend/shadow/scoring/embed.py` (`Wav2Vec2Embedder._load`), `backend/shadow/scoring/sounds/charctc.py`
  (`CharCtc._load`), `backend/shadow/main.py` (lifespan)
- Test: `backend/tests/test_hf.py`, `backend/tests/test_warm_up.py`

**Interfaces:**
- Produces: `wav2vec2_classes() -> tuple[type, type, type]` returning `(Wav2Vec2Model, Wav2Vec2ForCTC,
  Wav2Vec2CTCTokenizer)`, imported once under a module lock; `warm_up_steps(deps: Deps, device: str) ->
  list[Callable[[], threading.Thread]]` in `shadow/main.py`; `start_warm_ups(deps: Deps, device: str) ->
  threading.Thread` running the steps one after another (each step's thread joined before the next starts).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_hf.py
def test_wav2vec2_classes_import_once_across_threads(monkeypatch):
    import threading, shadow.hf as hf
    calls = []
    monkeypatch.setattr(hf, "_classes", None)
    monkeypatch.setattr(hf, "_import", lambda: (calls.append(1), ("M", "C", "T"))[1])
    threads = [threading.Thread(target=hf.wav2vec2_classes) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
    assert calls == [1] and hf.wav2vec2_classes() == ("M", "C", "T")

# tests/test_warm_up.py  (fake deps: objects with warm_up() returning a started thread that records its name)
def test_cpu_warms_only_the_recogniser(): ...      # warm_up_steps(deps, "cpu") -> only asr.warm_up
def test_cuda_warms_recogniser_embedder_sounds_in_order(): ...   # order asr, embedder, sounds.chars
def test_steps_run_one_at_a_time(): ...            # start_warm_ups: no two fake loads overlap (record enter/exit)
```

Fake classes must be recognised as real for the isinstance checks the lifespan uses today: the helper takes the
objects to warm from `deps` by attribute (`deps.asr`, `deps.embedder`, `deps.sounds.chars`) and checks a
`warm_up` attribute, not the concrete class.

- [ ] **Step 2: Run to see them fail**

Run: `cd backend && uv run pytest tests/test_hf.py tests/test_warm_up.py -q`
Expected: FAIL (module/functions missing).

- [ ] **Step 3: Implement**

`shadow/hf.py`: `_import()` does `from transformers import Wav2Vec2Model, Wav2Vec2ForCTC, Wav2Vec2CTCTokenizer`;
`wav2vec2_classes()` caches `_classes` under a `threading.Lock`. `Wav2Vec2Embedder._load` and `CharCtc._load` take
their classes from it. In `main.py`, the lifespan replaces the three separate warm-up calls with
`warm = start_warm_ups(deps, settings.resolved_device())` and keeps `watch_sounds_warm_up(deps, warm)` when the
sounds model is warmed (CUDA only). On `cpu` only the recogniser warms (spec §5.1: the tone embedder and char-CTC load
on the first take).

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add backend/shadow/hf.py backend/shadow/scoring/embed.py backend/shadow/scoring/sounds/charctc.py backend/shadow/main.py backend/tests/test_hf.py backend/tests/test_warm_up.py
git commit -m "fix(startup): import transformers once; warm models one at a time; practice models lazy on CPU"
```

### Task 3: Pause splitting behind a punctuation switch

**Files:**
- Create: `backend/shadow/ingest/pauses.py`
- Modify: `backend/shadow/config.py` (`ModelsCfg.punctuation: bool = True`; `SegmentationCfg.pause_cut_s: float = 0.5`,
  `pause_split_s: float = 0.25`, `min_chars: int = 4`, `max_chars: int = 25`), `backend/shadow/ingest/asr.py`
  (`ParaformerASR.__init__(model_id, device, punctuation: bool = True, segmentation: SegmentationCfg | None = None)`;
  `transcript_from_funasr(result, pauses: SegmentationCfg | None = None)`), `backend/shadow/deps.py` (pass both),
  `config.toml` (`[models] punctuation = true`, `[segmentation]` new keys)
- Test: `backend/tests/test_pauses.py`, `backend/tests/test_asr.py`

**Interfaces:**
- Produces: `pause_ranges(chars: list[TimedChar], cfg: SegmentationCfg) -> list[tuple[int, int]]` — contiguous
  inclusive `(first, last)` ranges covering every index of `chars`. `transcript_from_funasr(result, pauses=cfg)`
  builds one transcript segment per pause range when the text holds no punctuation; with punctuation, or `pauses`
  None, it behaves as today. `ParaformerASR` with `punctuation=False` loads no `punc_model` and calls
  `transcript_from_funasr(..., pauses=segmentation)`.

- [ ] **Step 1: Write the failing tests**

Build chars with a helper `chars(spec)` taking `(text, gap_after)` pairs, 0.24 s per character.

```python
def test_cuts_at_long_gaps():                    # "我是学生"(0.6 s gap)"我是中国人" -> [(0,3),(4,8)]
def test_never_cuts_inside_a_word():             # 0.7 s gap between 中 and 国 of 中国 -> no cut there
def test_long_piece_split_at_largest_gap():      # 30 chars, gaps 0.3 at 12 and 0.27 at 20 -> cut after 12 only
def test_no_gaps_still_splits_long_text_at_word_boundaries():  # 40 chars, all gaps 0.0 -> every piece <= 25, cuts at word ends
def test_short_piece_merges_across_smaller_gap():  # "好"(0.6)"我是学生"(0.9)... -> 好 joins the next piece
def test_short_transcript_is_one_piece():        # "好" and "你好" -> [(0,0)] / [(0,1)]
def test_ranges_cover_every_char_once():         # property over a 200-char random-gap fixture (seeded)
def test_unpunctuated_funasr_result_segments_by_pauses():  # transcript_from_funasr({"text": "我 是 ...", "timestamp": [...]}, pauses=SegmentationCfg()) -> tr.segments == pause ranges
def test_punctuated_result_ignores_pauses():     # with "。" in text the segments are today's sentence_ranges
```

- [ ] **Step 2: Run to see them fail**

Run: `cd backend && uv run pytest tests/test_pauses.py -q`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement `pause_ranges`**

Gap after index k = `chars[k+1].start - chars[k].end`. A boundary after k is allowed unless k is inside a `jieba`
word of the joined text (word ends computed once with `jieba.cut`). Algorithm:
1. Cut after every allowed k with gap ≥ `pause_cut_s`.
2. While a piece is longer than `max_chars`: among allowed k inside it leaving ≥ `min_chars` on each side, prefer
   gaps ≥ `pause_split_s`; if there are none, take any allowed k. Cut at the largest gap; ties go to the k nearest
   the piece's middle. If no k is allowed (one long word), leave the piece.
3. While a piece is shorter than `min_chars` and there is more than one piece: merge it across the smaller of its
   two neighbouring gaps (only one neighbour at the ends).

Then wire `transcript_from_funasr` and `ParaformerASR` as in Interfaces. Punctuation present means any character
`is_punct` in the text; such results keep today's `sentence_ranges`. The `_from_sentence_info` fallback also
re-segments with `pause_ranges` when `pauses` is given and its text holds no punctuation.

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest -q`
Expected: all pass (defaults unchanged: `punctuation = true`).

- [ ] **Step 5: Commit**

```bash
git add backend/shadow/ingest/pauses.py backend/shadow/ingest/asr.py backend/shadow/config.py backend/shadow/deps.py config.toml backend/tests/test_pauses.py backend/tests/test_asr.py
git commit -m "feat(ingest): pause-based sentence splitting behind [models] punctuation"
```

### Task 4: The splitting gate

**Files:**
- Create: `backend/shadow/ingest/splitcheck.py`, `backend/scripts/split_gate.py`, `backend/scripts/split_gate_urls.txt`
- Test: `backend/tests/test_splitcheck.py`

**Interfaces:**
- Consumes: `pause_ranges` (Task 3), `rectify_transcript` (`shadow/ingest/rectify.py`), `_subtitle_transcript`
  (`shadow/ingest/pipeline.py`), `YtDlpDownloader` / `choose_subtitle` (`shadow/ingest/youtube.py`).
- Produces: `SplitReport` dataclass (`precision, recall, f1, end_recall: float; pieces, over_25, over_30, under_4,
  inside_word: int`); `piece_ends(chars: list[TimedChar], ranges: list[tuple[int, int]]) -> list[float]` (end time of
  each piece but the last); `reference_breaks(tr: Transcript) -> tuple[list[float], list[float]]` (all human breaks,
  sentence-end breaks); `match(pred: list[float], ref: list[float], tol: float = 0.3) -> tuple[int, int, int]`
  (tp, fp, fn, greedy one-to-one nearest); `split_report(chars, ranges, ref_all, ref_ends) -> SplitReport`;
  `gate_passes(punc: SplitReport, pauses: SplitReport) -> bool`.
  `scripts/split_gate.py [--lessons 1 2 3 4] --out PATH` (urls from `split_gate_urls.txt`; Task 6 adds `--int8`).

- [ ] **Step 1: Write the failing tests**

```python
def test_match_one_to_one_within_tolerance():   # pred [1.0, 2.0, 5.0], ref [1.1, 5.5] -> (1, 2, 1)
def test_reference_breaks_from_cues_and_marks(): # two cues "我是学生，我很好" / "你呢" -> all = [after 生, after 好], ends = [after 好] (no 。 in file -> cue ends)
def test_reference_ends_use_full_stops_when_present():  # "我是学生。你呢？" in one cue -> ends at 。 and ？ positions
def test_split_report_counts_lengths_and_inside_word():  # ranges with a 31-char piece and a cut inside 中国
def test_gate_passes_needs_recall_f1_and_no_piece_over_30():
    a = SplitReport(precision=.9, recall=.8, f1=.85, end_recall=.9, pieces=10, over_25=0, over_30=0, under_4=0, inside_word=0)
    assert gate_passes(a, replace(a, f1=.86, end_recall=.9))
    assert not gate_passes(a, replace(a, end_recall=.89))
    assert not gate_passes(a, replace(a, f1=.84))
    assert not gate_passes(a, replace(a, f1=.9, end_recall=.95, over_30=1))
```

Reference rule: human breaks are cue ends plus every punctuation run inside a cue; sentence-end breaks are the
`。！？` positions when the subtitle text holds any, else the cue ends. A break's time is the end of the speech
character before it.

- [ ] **Step 2: Run to see them fail**

Run: `cd backend && uv run pytest tests/test_splitcheck.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement `splitcheck.py`**, then **Step 3b: write `scripts/split_gate.py`**

Per URL: probe, require `choose_subtitle` to return real Chinese subtitles (skip with a printed reason otherwise),
download audio and subtitles into `<data_dir>/cache/split-gate/<video id>/` (reused on reruns), normalise, transcribe
once with punctuation on (`ParaformerASR(..., punctuation=True)` on the resolved device). Candidate "punctuation" = `rectify_transcript(tr)`; candidate "pauses" = `pause_ranges` over the same
characters with punctuation removed. Reference = `reference_breaks(_subtitle_transcript(subtitle, tr)[0])`. Lessons
from `--lessons` use their stored transcript and their stored segment boundaries as the reference (read-only DB).
Write a markdown report: a table per source and a total (`SplitReport` for both candidates), the gate verdict from
`gate_passes` on the totals, and the first 15 pieces of both candidates for the first two videos.

- [ ] **Step 4: Pick the videos and run the gate**

Choose ≥ 4 natural-speed Mandarin videos, ≥ 30 minutes in total (interviews, native vlogs), whose
`uv run yt-dlp --list-subs <url>` shows `zh-Hans`, `zh-CN`, `zh-TW` or `zh` under **Available subtitles** (not only
automatic captions). Put the URLs in `scripts/split_gate_urls.txt`, one per line with a `#` comment naming the
channel. Run on the GPU machine with the backend stopped:
`cd backend && uv run python scripts/split_gate.py --lessons 1 2 3 4 --out ../data/reports/split-gate.md`
Expected: the report prints PASS or FAIL.

- [ ] **Step 5: The user decides**

Show the user the totals and the two printed samples. On PASS and the user's go, record it in the Ledger; Task 7
switches the default. On FAIL, stop and bring the numbers and the fallback (a small int8 punctuation model, spec §5.2)
to the user before continuing.

- [ ] **Step 6: Run tests and commit**

Run: `cd backend && uv run pytest -q` → all pass.

```bash
git add backend/shadow/ingest/splitcheck.py backend/scripts/split_gate.py backend/scripts/split_gate_urls.txt backend/tests/test_splitcheck.py docs/superpowers/plans/2026-10-22-laptop-fit.md
git commit -m "feat(scripts): sentence-splitting gate against human subtitles"
```

### Task 5: int8 models on the CPU

**Files:**
- Create: `backend/shadow/quant.py`
- Modify: `backend/shadow/config.py` (`ModelsCfg.int8: bool = False`, `ModelsCfg.threads: int = 0`),
  `backend/shadow/ingest/align.py` (`MmsAligner.__init__(device, int8: bool = False)`,
  `make_aligner(name, device, int8: bool = False)`), `backend/shadow/scoring/sounds/charctc.py`
  (`CharCtc.__init__(name, revision, device, int8: bool = False)`), `backend/shadow/ingest/asr.py`
  (`ParaformerASR(..., int8: bool = False)`), `backend/shadow/deps.py`
- Test: `backend/tests/test_quant.py`

**Interfaces:**
- Produces: `quantize_linear(module: torch.nn.Module) -> torch.nn.Module` (dynamic qint8 over `torch.nn.Linear`,
  eval mode); `int8_wanted(settings: Settings) -> bool` (`settings.models.int8` and device resolves to `cpu`);
  `cpu_threads(settings: Settings) -> int` (`models.threads` if > 0, else `max(1, physical cores - 1)` via
  `psutil.cpu_count(logical=False)`, falling back to `os.cpu_count()`). `build_deps` calls
  `torch.set_num_threads(cpu_threads(settings))` on `cpu` and passes `int8_wanted(settings)` to the three classes.
  Each class quantises right after loading its fp32 model (Paraformer: `AutoModel.model`), then runs
  `gc.collect()` and `trim_heap()`.

Note: `psutil` becomes a runtime dependency here (move it from the `dev` extra to `dependencies`).

- [ ] **Step 1: Write the failing tests**

```python
def test_quantize_linear_swaps_linear_layers_and_keeps_outputs_close():
    torch.manual_seed(0)
    m = torch.nn.Sequential(torch.nn.Linear(64, 64), torch.nn.ReLU(), torch.nn.Linear(64, 8))
    x = torch.randn(4, 64); ref = m(x)
    q = quantize_linear(m)
    assert isinstance(q[0], torch.ao.nn.quantized.dynamic.Linear)
    assert torch.allclose(q(x), ref, atol=0.05)

def test_int8_only_on_cpu():   # Settings(models=ModelsCfg(device="cuda", int8=True)) -> False; device="cpu" -> True; int8=False -> False
def test_cpu_threads_explicit_and_auto():   # threads=3 -> 3; threads=0 -> >= 1
```

Plus a `@pytest.mark.models` test: `MmsAligner("cpu", int8=True)` aligns a committed fixture WAV with its text and
returns one span per speech character.

- [ ] **Step 2: Run to see them fail**

Run: `cd backend && uv run pytest tests/test_quant.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement** as in Interfaces.

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest -q` → all pass; `cd backend && uv run pytest -m models tests/test_quant.py -q` → pass.

- [ ] **Step 5: Commit**

```bash
git add backend/shadow/quant.py backend/shadow/config.py backend/shadow/ingest/align.py backend/shadow/scoring/sounds/charctc.py backend/shadow/ingest/asr.py backend/shadow/deps.py backend/pyproject.toml backend/uv.lock backend/tests/test_quant.py
git commit -m "feat(models): int8 recogniser, aligner and sounds model on the CPU; thread cap"
```

### Task 6: int8 validation

**Files:**
- Create: `backend/scripts/int8_check.py`
- Modify: `backend/scripts/tone_model.py` (new `--stage evaluate` with `--int8-aligner`),
  `backend/tests/test_sounds_real.py` (device and int8 from `SHADOW_PARITY_DEVICE` / `SHADOW_INT8`; print caught % and
  false-alarm %)

**Interfaces:**
- Consumes: Task 5 flags, Task 4 `split_gate.py`, `aligncheck.energy_onset/onset_error`,
  `gate.text_similarity`, `ScoringCfg.min_text_similarity` (0.25) / `words_ok_at` (0.55).
- Produces: `int8_check.py align --lesson 1`, `int8_check.py words`, `int8_check.py cer`; each prints its numbers and
  PASS/FAIL against the Global Constraints. fp32 baselines run on the GPU (today's results), int8 candidates on the
  CPU; intermediate results are cached as JSON under `<data_dir>/cache/int8-check/` so the two halves can run in
  separate processes. Read-only on the user's DB.

- [ ] **Step 1: Write `int8_check.py`** — `align`: first-character onset error of fp32 MMS vs int8 MMS over the
  lesson's sentences (as `compare_aligners.py` measures it); `words`: for every stored take with a `score_json`,
  what the fp32 and the int8 recogniser hear, mapped to a verdict (`< 0.25` different words, `< 0.55` some words
  different, else clean) via `text_similarity`; agreement share; `cer`: character error rate of int8 vs fp32
  transcripts (punctuation removed) over the split-gate audio.
- [ ] **Step 1b: Add `--int8` to `split_gate.py`** — transcribe with `ParaformerASR(..., punctuation=True,
  int8=True)` on the CPU; everything else as before.
- [ ] **Step 2: Add `--stage evaluate --int8-aligner` to `tone_model.py`** — recompute the held-out test speakers'
  features with the int8 aligner on the CPU (fp32 tone embedder) and evaluate the committed `tone_v1` without
  retraining; print native and altered accuracy and false-red next to the values stored in
  `shadow/scoring/models/tone_v1.json`.
- [ ] **Step 3: Run every check** (backend stopped):
  - `uv run python scripts/int8_check.py align --lesson 1`
  - `uv run python scripts/int8_check.py words`
  - `uv run python scripts/int8_check.py cer` and `uv run python scripts/split_gate.py --int8 --out ../data/reports/split-gate-int8.md`
  - `SHADOW_PARITY_DEVICE=cpu SHADOW_INT8=1 uv run pytest -m models tests/test_sounds_real.py -s -q`
  - `uv run python scripts/tone_model.py --labels realised --stage evaluate --int8-aligner`
  Expected: each prints PASS against the Global Constraints. Record all numbers in the Ledger.
- [ ] **Step 4: On a FAIL** — keep that model fp32 (its `int8` path off via a per-model switch in `build_deps`),
  note it in the Ledger, and let Task 7's budget run decide; if the budget then breaks, stop and bring the numbers to
  the user. If int8 shifts the sounds score distribution enough to fail, recalibrate the four z-normalisers and
  `fused_threshold` for the CPU build only as a separate `[sounds_cpu]` profile — and only with the user's go.
- [ ] **Step 5: Commit**

```bash
git add backend/scripts/int8_check.py backend/scripts/tone_model.py backend/tests/test_sounds_real.py docs/superpowers/plans/2026-10-22-laptop-fit.md
git commit -m "feat(scripts): int8 validation (alignment, words check, transcripts, sounds, tone)"
```

### Task 6b: Punctuation from the small sherpa-onnx model (added after the gate)

*Why:* the gate (Ledger) rejected pause splitting on natural speech (end recall 0.526 vs 0.783), and the user chose
to keep punctuation. A spike (`.superpowers/sdd/2026-10-22-laptop-fit/spike-punct/RESULTS.md`) measured the int8
sherpa-onnx CT-Transformer (`sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12`, `model.int8.onnx`,
72 MB): peak RSS 181 MB vs > 5 GB for `ct-punc`, end recall 0.797 vs 0.783, F1 0.759 vs 0.760. The user approved it
for every device.

**Files:**
- Create: `backend/shadow/ingest/punct.py`
- Modify: `backend/shadow/config.py` (`ModelsCfg.punctuation: str = "sherpa"` — values `"sherpa"` | `"pauses"`,
  replacing the bool; `ModelsCfg.punctuation_model: str =
  "sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8"`, `punctuation_url: str` (the sherpa-onnx
  GitHub release tarball for it), `punctuation_sha256: str` (pinned)), `backend/shadow/ingest/asr.py`
  (`ParaformerASR` never passes `punc_model` to FunASR; it punctuates through a `Punctuator`), `backend/shadow/deps.py`,
  `backend/scripts/split_gate.py` (the "punctuation" candidate now comes from the sherpa punctuator),
  `backend/pyproject.toml` (`sherpa-onnx` in the `models` extra), `backend/uv.lock`, `config.toml`
- Test: `backend/tests/test_punct.py`, `backend/tests/test_asr.py`

**Interfaces:**
- Produces: `class SherpaPunctuator(model: str, url: str, sha256: str, cache_dir: Path)` with `punctuate(text: str)
  -> str` (lazy `_load` under its own lock then `shadow.hf.model_load_lock`, `sherpa_onnx` imported through
  `shadow.hf.guarded_import`; first use downloads the tarball into `cache_dir/<model>/`, verifies SHA-256 before
  unpacking, refuses on mismatch); `models_cache_dir() -> Path` (`SHADOW_MODELS_DIR` env var, else
  `~/.cache/shadow-speech/models`); `punctuate_timed(text: str, timestamps: list[list[int]], punctuator: Punctuator,
  cfg: SegmentationCfg) -> str` — punctuates in chunks of ≤ 150 speech characters cut at the largest timestamp gaps
  (reuse `pause_ranges` with `max_chars=150`), joined in order, so marks never move between timed characters.
  `ParaformerASR(model_id, device, punctuator: Punctuator | None, segmentation, int8)`: with a punctuator,
  `_run` punctuates FunASR's unpunctuated text with `punctuate_timed` and passes the result to
  `transcript_from_funasr`; with `punctuation = "pauses"` it keeps the pause path. The words check (`try_transcribe`
  for `hear`) skips punctuation.

- [ ] **Step 1: Failing tests** — `test_punctuate_timed_keeps_characters_and_order` (fake punctuator inserting marks;
  stripping marks gives the input), `test_chunks_are_at_most_150_chars_and_cut_at_largest_gaps`,
  `test_download_refuses_bad_checksum` (urlopen monkeypatched), `test_paraformer_never_loads_ct_punc` (fake funasr:
  no `punc_model` kwarg for either setting), `test_asr_run_punctuates_with_sherpa` (fake punctuator → punctuated
  transcript, timestamps paired per unit), `test_hear_skips_punctuation`.
- [ ] **Step 2:** Run → FAIL. **Step 3:** Implement. **Step 4:** `uv run pytest -q` → pass; one `@pytest.mark.models`
  test that downloads the real model and punctuates a short sentence.
- [ ] **Step 5: Rerun the gate** with the sherpa candidate (`split_gate.py`, fresh transcripts) under the watchdog:
  sherpa end recall and F1 within 2 points of the spike's (0.797 / 0.759). Record in the Ledger.
- [ ] **Step 6: Commit** `feat(ingest): punctuation from the small sherpa-onnx model; FunASR's ct-punc dropped`.

### Task 7: Switch the defaults and prove the budget

**Files:**
- Modify: `config.toml`, `README.MD` (How a lesson is made; CPU requirements), `docs/running.md` (CPU only:
  `int8 = true`, `threads`), possibly the model classes (conditional Step 3)

- [ ] **Step 1: Defaults and remaining int8 checks** — `punctuation = "sherpa"` is already the default (Task 6b).
  `int8` stays `false` in the repo's `config.toml` (the GPU machine); the laptop config written by the Windows plan
  sets `int8 = true`. Run the two int8 checks that could not run while `ct-punc` was in place: `split_gate.py --int8`
  and `int8_check.py cer` (pass marks in Global Constraints). Record them in the Ledger.
- [ ] **Step 2: Budget run**

Run: `cd backend && CUDA_VISIBLE_DEVICES="" uv run python scripts/cpu_budget.py --clip <5-min clip> --device cpu --int8 --threads 4 --budget`
Expected: exit 0, every phase within budget. Record phases, peaks and per-take seconds in the Ledger.

- [ ] **Step 2b: Long video** — make a 60-minute clip (concatenate lesson sources with ffmpeg) and run
  `... cpu_budget.py --clip <60-min clip> --device cpu --int8 --threads 4 --phases startup,build --budget`.
  Expected: build peak ≤ 3.5 GB. If it is over, lower the recogniser's `batch_size_s` (today 300 in
  `ParaformerASR._run`) through a new `ModelsCfg.asr_batch_s: int = 300` until it fits, and record the value.

- [ ] **Step 3 (only if a load-time peak breaks the budget): store int8 weights** — on first load, save each
  quantised model's `state_dict` to `<model cache>/int8/<model id>-<revision>.pt`; later loads build the
  architecture without fp32 weights (`transformers`: `from_config` under `torch.device("meta")` then
  `to_empty`; MMS/Paraformer: the same pattern), apply `quantize_linear`, and `load_state_dict` the stored int8
  weights. Add a `models` test that a second load gives identical outputs. Rerun Step 2.
- [ ] **Step 4: Docs** — README "How a lesson is made": sentences split at pauses (subtitled videos keep their
  punctuation); requirements: CPU works, 8 GB RAM with `int8 = true`. `docs/running.md` CPU section: `int8`, `threads`,
  `punctuation`.
- [ ] **Step 5: Full check and commit**

Run: `make test` → passes.

```bash
git add backend/shadow config.toml README.MD docs/running.md backend/tests docs/superpowers/plans/2026-10-22-laptop-fit.md
git commit -m "feat: pause splitting by default; laptop budget met with int8 on the CPU"
```

---

## Ledger

| Item | Result |
|---|---|
| Baseline budget run (Task 1) | `--device cpu --threads 4` (ran with 5 threads, cores - 1: `build_deps` reset the count the script set; fixed afterwards, numbers stand as measured), default adaptive cap (about 4100 MB on this machine). Startup peaks 738 MB (models load lazily). Build phase: the watchdog aborted with exit 3 at 4143 MB (cap 4104 MB), phase build. Earlier runs with the 5000 MB cap were killed by the kernel (exit 137) at a watched peak of 3689 MB, and some runs (also with the adaptive cap) ended early with a job error (funasr "Cannot copy out of meta tensor", peak about 2.6 GB), which is attributed to concurrent model loading. Practice and build+practice never reached. |
| Gate videos and verdict (Task 4) | FAIL (fp32, GPU, after the transcript fixes). 6 videos, all usable, 93.2 min (zbbXDcuILDs 0.91, Zp1yfsb2SDQ 0.88, K2vBHUUqWoI 0.93, Za6c0NcAmOk 0.93, t7ZI9c6Ze7E 0.92, snZ811wvjjw 0.94). Videos total, punctuation vs pauses: end recall 0.783 vs 0.526, F1 0.760 vs 0.557, pieces over 30: 12 vs 0, inside-word cuts 6 vs 0, pieces under 4: 162 vs 0, pieces 2253 vs 1613. Pauses beat punctuation on length and word integrity, but miss about a third more human sentence ends. Gate with --int8 (CPU): aborted at the cap (RSS 5159 MB > 5000 MB, loading ct-punc, which stays fp32 in that script); not run. CER int8 vs fp32: not run (needs the int8 gate transcripts). |
| User's go on pause splitting | Decision 2026-10-23: pause splitting rejected (the gate failed); punctuation comes from the int8 sherpa-onnx model. |
| User's int8 decisions (2026-10-23) | Recogniser int8 only on a machine with less than 12 GB RAM (`asr_int8_below_ram_gb`), fp32 above (words agreement 93.9 % and CER 3.35 % were the shortfalls); `int8_skip` still overrides. Sounds int8 accepted (5.3 % false alarms, 86 % caught); aligner int8 everywhere on the CPU. Practising budget 3.0 -> 3.1 GB. |
| int8: alignment / words / CER + gate / sounds / tone (Task 6) | Ran (cap 4000 MB, dev server up). Alignment (lesson 1, 56 sentences): mean onset error fp32 66.1 ms, int8 66.4 ms (+0.3 ms): PASS. Tone (32 held-out speakers, int8 aligner, fp32 embedder): native 0.9442 (stored 0.9443), altered 0.9525 (0.9526), false red 0.0535 (0.0533): all within 0.02 points: PASS. Words check (313 stored takes): verdict agreement 93.9 % (< 95 %): FAIL; clean/some/different fp32 257/49/7, int8 263/43/7; most disagreements are takes near the 0.55 line and int8 hears the sentence more often than fp32 (checked by eye), but the mark is fixed. `ModelsCfg.int8_skip` (R2) added, empty by default; Task 7 decides whether to set `["asr"]`. Words control (dev server stopped): fp32 on CPU vs fp32 on GPU agree 100.0 % (313 takes), so the 93.9 % is int8 itself, not numerical noise. Sounds parity int8 on the CPU (29 slip pairs, 207 normal syllables): caught 25/29 = 86.2 % (>= 76 %: PASS), false alarms 11/207 = 5.3 % (<= 5 %: FAIL by 0.3 points), wrong heard 0. Pending (need ct-punc, rescheduled after merge): CER + split gate with int8. |
| Task 6b Step 5: gate with the sherpa punctuation (fp32, GPU, fresh transcripts) | Videos total, punctuation: end recall 0.788, F1 0.755 (spike 0.797 / 0.759: within 2 points: PASS). The pause-vs-punctuation gate still FAILS, as decided (pauses end recall 0.530, F1 0.560). |
| Task 7 Step 1: int8 | Split gate with int8 timestamps (CPU): videos total, punctuation end recall 0.797, F1 0.759, equal to the spike, pieces over 30: 4 (fp32 5): PASS for the sherpa splitter (the pauses-beat-punctuation gate itself is FAIL, as in fp32). CER int8 vs fp32 over 9 sources, 26675 characters: 3.35 % (mark 2 %): FAIL. |
| Budget run with int8 (Task 7) | Found: loading peaks, not weights. Sounds model stayed 1.2 GB resident after quantising (checkpoint mmap kept alive), FunASR deep-copies the 0.9 GB checkpoint on load, torchaudio builds MMS twice. Fixes: `quantize_linear` copies tensors out of the mapping and quantises Linear by Linear; the FunASR deepcopy is skipped during the load; MMS built on the meta device; the int8 sounds and MMS models are stored once (`<SHADOW_MODELS_DIR>/int8/`, default `~/.cache/shadow-speech/models/int8/`) and later loads read int8 only. 5-min clip, `--device cpu --int8 --threads 4` (ran with 5 threads, cores - 1, because `build_deps` reset the count the script set; fixed afterwards, numbers stand as measured), warm int8 cache (every run had the int8 copies already stored: cold-cache peaks were not measured, see `--cold-int8`): startup 729-733 MB, build 2830-2855 MB (PASS), practice 3036-3099 MB (budget 3000: over by 36-99 MB), build+practice 2967-3108 MB (PASS in the best run, 3108 in another). Per-take seconds 2.1-7.9 (first take 7.9-10.5 s: loads). Before the fixes: build 3989, practice 3831, build+practice 4063. 64-min clip, startup+build: build 2925 MB in 1628 s (PASS, `asr_batch_s` not needed; before the fixes 4043 MB, aborted at the cap). int8_skip not run (it adds the fp32 recogniser, about 0.5 GB). |
