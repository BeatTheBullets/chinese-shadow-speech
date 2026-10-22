# Phase 3a — Wrong-sound detection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a scored take, mark syllables whose initial/final was a confusable partner (chī said as cī), show what was heard in a HEARD row, let the user click his own syllables to hear them, and carry sound slips into Stats (Sounds panel) and Drills (`sound` focus).

**Architecture:**
- New backend package `shadow/scoring/sounds/` ports the 3a spike's detector:
  - `contrasts.py`: partners, directions and labels (pure)
  - `gop.py`: CTC goodness-of-pronunciation (pure torch)
  - `decide.py`: z-fusion decision (pure)
  - `charctc.py`: the wav2vec2 char-CTC model, "B"
  - `detector.py`: per-take `SoundDetector.check`, using the app's MMS model ("A") and B
- `score_take` calls the detector after tone judging and stores the result per syllable in `score_json` and in `SyllableScore`.
- Stats and drill code read the new columns.
- Frontend:
  - TwoTrack gains a HEARD row, purple rings on the reference row, and clickable You cells.
  - Stats gains a Sounds panel; drills learn the `sound` kind.

**Tech Stack:** FastAPI, SQLModel/SQLite, torch/torchaudio, transformers, pypinyin, pytest; React 18, Vite 5, vitest 3, Tailwind (all existing).

**Spec:** `docs/superpowers/specs/2026-10-22-phase3a-sounds-design.md`. Read it first. Section numbers below (§n) refer to it. The spike code it ports is in `.superpowers/sdd/p3a-spike/`, mainly `common.py` (`partners`), `gop.py`, `method_a.py` and `method_b.py`. It is git-ignored but present on this machine.

## Global Constraints

- **Detector constants**, verbatim, in `SoundsCfg` (`[sounds]` in `config.toml`):
  - `enabled = true`
  - `model = "wbbbbb/wav2vec2-large-chinese-zh-cn"`
  - `revision = "b654b5f3df69725df32808de454a1b865c829e4c"`
  - `z_a_mean = -4.006537`, `z_a_sd = 2.974512`
  - `z_b_mean = 1.239741`, `z_b_sd = 3.072057`
  - `fused_threshold = 5.3036`
  - `b_only_threshold = 11.6518`
- **Port the spike faithfully.** No fp16, no "improvements" to windows, normalisation or partner rules. The model regression test (Task 6) is the parity gate: ≥ 22/29 slips marked, ≤ 6 % false marks over all normal-take syllables, and the heard syllable equals the planned slip on every marked slip.
- **The syllable inventory is frozen.** Copy `.superpowers/sdd/p3a-spike/valid_syllables.json` (552 toneless syllables, ü written `v`) to `backend/shadow/scoring/models/syllables_v1.json`.
- **Sound slips never change `overall` / `tone_overall`.** `segmental_overall` stays `null`.
- **A sound failure never fails a take.** Any exception in sound checking gives `sound: null` for every syllable, `sounds_off: null` and `sounds_checked: null`. Tone results are stored as normal.
- **Purple (`sound: '#c678dd'` in Tailwind) is used only for sound marks.** Tone colours are unchanged.
- **The HEARD pinyin carries the dictionary tone** (the `words_json` tone, as in the reference row above it), never `target_tone`. Tone 0 means no mark.
- **Direction keys** are `"<expected>><heard>"`. The complete set is fixed in Task 1. URLs carry them through `encodeURIComponent`.
- **Memory.** Backend runs in WSL2 (8 GB VRAM, 7.7 GB RAM, backend ≈ 5.3 GB RSS when warm); the user games on the same PC.
  - Jobs that load models outside the backend (model tests, back-fill) need the user to stop the backend first. The controller asks him.
  - CPU threads are capped at 4 for long jobs (`OMP_NUM_THREADS=4`).
- **Commands.**
  - Backend: `cd backend && ~/.local/bin/uv run pytest -q`. Never `uv sync` without `--extra dev --extra models`.
  - Model tests: `cd backend && OMP_NUM_THREADS=4 ~/.local/bin/uv run pytest -q -m models tests/test_sounds_real.py`.
  - Frontend: `cd frontend && npm test -- --run && npx eslint . && npx tsc -b`. There is one pre-existing Drawer.tsx eslint warning.
- **Code style.** Match the surrounding code: dense why-comments, `from __future__ import annotations`, no abstractions beyond those named here.
- **Commits.** End with a blank line and the Co-Authored-By line of the session that writes them.

## Review Focus

- **Syllables the detector cannot judge** must come back `sound: null`, never as a crash or a false slip. These are: non-hanzi (tone −1), erhua 儿 / `er`, a syllable not in the inventory, a `missing` or `unvoiced` status, and a partner only A knows (ding/din). Test: Task 5 `test_check_skips_unjudgeable_syllables`.
- **A window at the very start or end of the take** that must be widened past the audio bounds must still give a finite GOP. Test: Task 2 `test_win_gop_widens_at_edges`.
- **Takes scored before this phase** (no `sound` key, no `sounds_off`), and Flow takes, must render exactly as today: no HEARD row, no chip. Test: Task 11 `renders as before without sound fields`.
- **The B model failing**, at load or mid-take, must leave the tone score stored, sounds null and the chip hidden, and `/health` must say why. Test: Task 7 `test_sound_failure_keeps_tone_score`.
- **A sound-drill target that could not be checked in a take** counts as not ok, so the item cannot go green on it. Test: Task 9 `test_sound_green_needs_every_target_checked_ok`.

## File Structure

**Backend, new:**
- `shadow/scoring/sounds/__init__.py`
- `contrasts.py`, `gop.py`, `decide.py`, `charctc.py`, `detector.py`, `backfill.py` in that package
- `shadow/scoring/models/syllables_v1.json`
- `scripts/backfill_sounds.py`
- Tests:
  - `tests/test_sound_contrasts.py`
  - `tests/test_sound_gop.py`
  - `tests/test_sound_decide.py`
  - `tests/test_sound_detector.py`
  - `tests/test_sounds_real.py` (models)
  - `tests/test_sound_backfill.py`

**Backend, modified:**
- `config.toml`
- `shadow/config.py`: `SoundsCfg`
- `shadow/ingest/align.py`: `MmsAligner.emissions` / `letter_ids`, `LockedAligner` forwarding
- `shadow/store/models.py`: two columns
- `shadow/scoring/score.py`, `shadow/scoring/__init__.py`, `shadow/deps.py`, `shadow/main.py`, `shadow/api/health.py`, `shadow/api/stats.py`
- `shadow/drill/queue.py`, `shadow/drill/summary.py`, `shadow/drill/focus.py` (label), `shadow/api/drill.py`
- `Makefile`
- Tests:
  - `tests/test_score.py`
  - `tests/test_scoring_api.py`
  - `tests/test_stats_api.py`
  - `tests/test_drill_queue.py`
  - `tests/test_drill_api.py`

**Frontend, new:**
- `src/components/HeardRow.tsx` (+ test)
- `src/components/SoundsPanel.tsx` (+ test)

**Frontend, modified:**
- `tailwind.config.ts`
- `src/api/types.ts`, `src/api/client.ts`
- `src/lib/cells.ts`, `src/lib/score.ts` (+ tests)
- `src/components/CellRow.tsx`, `TwoTrack.tsx`, `ScoreHeader.tsx` (+ tests)
- `src/pages/Practice.tsx`, `src/components/DrillRunner.tsx`: play your syllable, sound green
- `src/lib/drill.ts` (+ test)
- `src/pages/Stats.tsx` (+ test)

**Docs:** `README.MD`, `docs/phase3a-acceptance.md` (new).

---

### Task 1: Contrasts, directions, labels, toned pinyin

**Files:**
- Create: `backend/shadow/scoring/sounds/__init__.py` (empty docstring), `backend/shadow/scoring/sounds/contrasts.py`, `backend/shadow/scoring/models/syllables_v1.json` (copy, see Global Constraints)
- Test: `backend/tests/test_sound_contrasts.py`

**Interfaces:**
- Produces, all in `contrasts.py`:
  - `inventory() -> frozenset[str]`
  - `partners(s: str) -> list[tuple[str, str]]`: (partner, contrast name). This is the spike's `common.partners`: same tables, same order, partner must be in the inventory and differ from `s`, no duplicates.
  - `direction(expected: str, heard: str) -> str | None`
  - `directions_of(s: str) -> set[str]`: the directions of all `partners(s)`.
  - `DIRECTIONS: tuple[str, ...]`
  - `direction_label(key: str) -> str`
  - `drill_label(key: str) -> str`
  - `heard_pinyin(toneless: str, tone: int) -> str`

Direction keys, one per ordered contrast pair:

| Group | Keys |
|---|---|
| initials | `zh>z z>zh ch>c c>ch sh>s s>sh r>l l>r f>h h>f` |
| -n/-ng | `ng>n n>ng`, from any of an/ang, en/eng, in/ing, ian/iang, uan/uang |
| ü/u | `ü>u u>ü`, from lv/lu, nv/nu, yu/wu |
| vowels | `ai>ei ei>ai ao>ou ou>ao ou>uo uo>ou an>en en>an ang>eng eng>ang` |

Labels:

| Function | Initials | -n/-ng | ü/u | vowels |
|---|---|---|---|---|
| `direction_label` | `"ch said as c"` | `"-ng said as -n"` | `"ü said as u"` | `"ou said as uo"` |
| `drill_label` | `"ch (not c)"` | `"-ng (not -n)"` | `"ü (not u)"` | `"ou (not uo)"` |

- [ ] **Step 1: Write the failing tests**

```python
from shadow.scoring.sounds.contrasts import (DIRECTIONS, direction, direction_label, directions_of, drill_label,
                                             heard_pinyin, inventory, partners)

def test_inventory_is_the_spike_list():
    inv = inventory()
    assert len(inv) == 552 and "nv" in inv and "chi" in inv and "din" in inv   # din: no characters in B (Task 5)

def test_partners_match_the_spike():
    assert partners("chi") == [("ci", "ch/c")]
    assert partners("zen") == [("zhen", "zh/z"), ("zeng", "n/ng"), ("zan", "vowel")]
    assert partners("sheng") == [("seng", "sh/s"), ("shen", "n/ng"), ("shang", "vowel")]
    assert partners("dou") == [("dao", "vowel"), ("duo", "vowel")]
    assert partners("nv") == [("nu", "ü/u")] and partners("yu") == [("wu", "ü/u")]
    assert partners("wo") == [] and partners("de") == [] and partners("er") == []
    assert partners("ding") == [("din", "n/ng")]

def test_direction():
    assert direction("chi", "ci") == "ch>c" and direction("zen", "zhen") == "z>zh"
    assert direction("ping", "pin") == "ng>n" and direction("jin", "jing") == "n>ng"
    assert direction("yu", "wu") == "ü>u" and direction("nu", "nv") == "u>ü"
    assert direction("dou", "duo") == "ou>uo" and direction("men", "man") == "en>an"
    assert direction("chi", "shi") is None
    assert set(DIRECTIONS) >= {d for s in inventory() for d in directions_of(s)}

def test_labels_and_heard_pinyin():
    assert direction_label("ch>c") == "ch said as c" and direction_label("ng>n") == "-ng said as -n"
    assert drill_label("ü>u") == "ü (not u)"
    assert heard_pinyin("ci", 1) == "cī" and heard_pinyin("nv", 3) == "nǚ" and heard_pinyin("de", 0) == "de"
```

- [ ] **Step 2: Run them and see them fail**

`cd backend && ~/.local/bin/uv run pytest -q tests/test_sound_contrasts.py`. Expected: ImportError.

- [ ] **Step 3: Implement `contrasts.py`**

- `inventory()` reads the JSON once (module cache).
- `heard_pinyin` uses `pypinyin.contrib.tone_convert.to_tone(f"{toneless}{tone}")`; tone ≤ 0 means the plain toneless with `v` → `ü`.
- `direction` derives the key from the contrast name `partners` gives:
  - initials: the two initials
  - n/ng: `ng>n` when the expected final ends in `ng`, else `n>ng`
  - ü/u: `ü>u` when the expected syllable is `lv`/`nv`/`yu`
  - vowel: the two finals
  - not a partner: `None`

- [ ] **Step 4: Run the tests and see them pass**

- [ ] **Step 5: Commit**

`git add backend/shadow/scoring/sounds backend/shadow/scoring/models/syllables_v1.json backend/tests/test_sound_contrasts.py && git commit -m "feat(sounds): contrast partners, directions and labels"`

---

### Task 2: CTC GOP core

**Files:**
- Create: `backend/shadow/scoring/sounds/gop.py`
- Test: `backend/tests/test_sound_gop.py`

**Interfaces:**
- Produces:
  - `ctc_ll(logp: torch.Tensor, targets: list[list[int]], blank: int) -> np.ndarray`: log P(target | frames) per target. Port spike `gop.ctc_ll` as is (cudnn disabled, `reduction="none"`).
  - `utt_gops(logp, blank: int, seq: list[list[int]], alts: list[list[list[int]]]) -> list[tuple[float, int] | None]`: per syllable i, `ll(full) − max_k ll(full with syllable i replaced by alts[i][k])`, plus the argmax k. Returns None when `alts[i]` is empty. All hypotheses go in one `ctc_ll` call.
  - `win_gop(logp, blank: int, target: list[int], alts: list[list[int]], win: tuple[float, float], frame_s: float) -> float | None`: spike `score_side`'s `win` term. `frames_of(win, frame_s, T, pad=0)`; widen one frame each side while `b − a < max(need(t) for t in [target, *alts]) + 1` and the bounds allow; `ll(target) − max ll(alts)` over `logp[a:b]`. None without alts.

- [ ] **Step 1: Write the failing tests**
  - `test_ctc_ll_prefers_the_spoken_sequence`: build a T=12 × C=4 log-prob matrix whose frames clearly spell blank,1,1,blank,2,2,blank… (log 0.97 on the intended class, the rest spread). Assert `ctc_ll(lp, [[1,2],[1,3]], 0)` has `[0] > [1] + 5`.
  - `test_utt_gops_returns_margin_and_best_alt`: same matrix; `seq=[[1],[2]]`, `alts=[[], [[3],[1]]]`. Assert the result is `[None, (g, k)]` with `g > 0`, and `k` is the index of the likelier alt.
  - `test_win_gop_widens_at_edges`: a window `(0.0, 0.001)` at frame 0 with `frame_s=0.02` and a 3-label target. Assert a finite float and no exception; with `alts=[]`, None.

- [ ] **Step 2: Run them and see them fail**
- [ ] **Step 3: Implement `gop.py`**, porting `ctc_ll`, `need` and `frames_of` verbatim from the spike.
- [ ] **Step 4: Run the tests and see them pass**
- [ ] **Step 5: Commit** `feat(sounds): CTC goodness-of-pronunciation core`

---

### Task 3: Config and the fusion decision

**Files:**
- Modify: `backend/shadow/config.py` (add `SoundsCfg` and a `sounds` field on `Settings`), `config.toml` (`[sounds]` with the Global Constraints values)
- Create: `backend/shadow/scoring/sounds/decide.py`
- Test: `backend/tests/test_sound_decide.py`, `backend/tests/test_config.py` (the `[sounds]` defaults load)

**Interfaces:**
- Produces:
  - `SoundsCfg(enabled, model, revision, z_a_mean, z_a_sd, z_b_mean, z_b_sd, fused_threshold, b_only_threshold)`
  - `decide(bad_a: float | None, bad_b: float | None, cfg: SoundsCfg) -> tuple[str, float, str] | None`, returning (status `"ok"|"slip"`, z, rule `"fused"|"b_only"`):
    - both present: `z = (bad_a − z_a_mean)/z_a_sd + (bad_b − z_b_mean)/z_b_sd`; slip when `z > fused_threshold`; rule `"fused"`.
    - only `bad_b`: slip when `bad_b > b_only_threshold`; z = `(bad_b − z_b_mean)/z_b_sd`; rule `"b_only"`.
    - otherwise None (only A, or neither).

- [ ] **Step 1: Write the failing tests**, with these cases:
  - `decide(0.28, 6.78, cfg)`: z ≈ 1.448 + 1.804, so `"ok"`.
  - `decide(10.0, 20.0, cfg)`: `"slip"`, `"fused"`.
  - `decide(None, 28.0, cfg)`: `"slip"`, `"b_only"`.
  - `decide(None, 1.5, cfg)`: `"ok"`, `"b_only"`.
  - `decide(3.0, None, cfg) is None` and `decide(None, None, cfg) is None`.
- [ ] **Step 2: Run them and see them fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the tests and see them pass**
- [ ] **Step 5: Commit** `feat(sounds): config and fusion decision`

---

### Task 4: The char-CTC model (B), and the memory gate

**Files:**
- Create: `backend/shadow/scoring/sounds/charctc.py`
- Test: `backend/tests/test_sound_detector.py` (the group-matrix part)

**Interfaces:**
- Produces:
  - `group_matrix(vocab: dict[str, int], size: int, blank: int, syllables: list[str]) -> np.ndarray`: shape `size × (1 + len(syllables))`. Column 0 is blank. A single-hanzi token counts for every `pypinyin` reading (`heteronym=True`, `Style.NORMAL`, lower case, ü → v) that is in `syllables`. Spike `method_b.py` lines 25–33.
  - `class CharModel(Protocol)`, with:
    - `blank: int`
    - `group_logp(wav: np.ndarray, sr: int) -> torch.Tensor`: T × (1+S) log group probabilities
    - `sid(s: str) -> int | None`: the group column of a syllable that has at least one character; otherwise None
  - `class CharCtc(CharModel)`, `CharCtc(name: str, revision: str, device: str)`. Built like `Wav2Vec2Embedder`: lazy `_load` under a `threading.Lock`, `warm_up() -> threading.Thread`, `_model` attribute for `loaded_models`.
    - Normalise the 16 kHz waveform to `(x − mean)/(std + 1e-7)`.
    - Compute `logits.softmax(-1) @ M`, then `.clamp_min(1e-30).log()`, all in fp32.
    - The vocab comes from the model's tokenizer (`Wav2Vec2CTCTokenizer.from_pretrained(name, revision=...)`, `get_vocab()`); `blank = config.pad_token_id`.
    - Load straight to the device with a small CPU-side peak, e.g. `from_pretrained(..., low_cpu_mem_usage=True)` then `.to(device)`.

- [ ] **Step 1: Write the failing test** `test_group_matrix_pools_heteronyms`: vocab `{"<pad>":0, "吃":1, "行":2, "a":3}`, syllables `["chi", "hang", "xing"]`. Assert `M[0,0]==1`, `M[1,1]==1`, `M[2,2]==M[2,3]==1`, `M[3].sum()==0`.
- [ ] **Step 2: Run it and see it fail**
- [ ] **Step 3: Implement `charctc.py`**
- [ ] **Step 4: Run the test and see it pass**
- [ ] **Step 5: Memory gate (controller; spec §6). Ask the user first.**
  1. the user's backend runs and is warm: one take scored since start.
  2. Record the baseline: `free -m`, swap used, `nvidia-smi --query-gpu=memory.used --format=csv`.
  3. In a second process, `OMP_NUM_THREADS=4 ~/.local/bin/uv run python -c "from shadow.scoring.sounds.charctc import CharCtc; import numpy as np, time; m=CharCtc('wbbbbb/wav2vec2-large-chinese-zh-cn','b654b5f3df69725df32808de454a1b865c829e4c','cuda'); m.group_logp(np.zeros(48000,np.float32),16000); time.sleep(60)"`.
  4. While it sleeps, record the same three numbers again.
  5. A separate process adds its own CUDA context, so this over-estimates. Pass when available RAM stays ≥ 1.0 GB, swap used grows < 200 MB, and VRAM used ≤ 7.5 GB.
  6. **On a fail, stop the plan and report the numbers to the user. Do not choose a fallback.**
  7. Write the numbers into the commit message.
- [ ] **Step 6: Commit** `feat(sounds): char-CTC model wrapper` (with the measured numbers)

---

### Task 5: MMS emissions and the per-take detector

**Files:**
- Modify: `backend/shadow/ingest/align.py`
  - `MmsAligner.emissions(wav, sr) -> tuple[torch.Tensor, float]`: the model's raw output `emission[0]` (exactly what `align` computes, **no extra log_softmax**, as in the spike) and seconds per frame.
  - `MmsAligner.letter_ids(syllable: str) -> list[int]`: `[dict[c] for c in s.replace("v","u") if c in dict] or [dict["a"]]`, with `dict = bundle.get_dict(star=None)`.
  - `MmsAligner.blank -> int`: the dictionary's blank index, 0 for MMS_FA; the spike used 0.
  - `LockedAligner` forwards all three under its lock, and exposes `inner` for `isinstance` checks.
- Create: `backend/shadow/scoring/sounds/detector.py`
- Test: `backend/tests/test_sound_detector.py`

**Interfaces:**
- Consumes:
  - Tasks 1–4.
  - `windows()` from `shadow.scoring.windows`.
- Produces:
  - `class LetterModel(Protocol)`: `blank: int`, `emissions(wav, sr) -> tuple[torch.Tensor, float]`, `letter_ids(s: str) -> list[int]`. `MmsAligner` and `LockedAligner` satisfy it.
  - `class Sounds(Protocol)`: `check(*, take: np.ndarray, sr: int, usr_win: list[tuple[float, float]], ref_wav: np.ndarray, ref_sr: int, ref_key: str, syllables: list[dict], statuses: list[str]) -> list[dict | None]`.
  - `class SoundDetector(Sounds)`, `SoundDetector(letters: LetterModel, chars: CharModel, cfg: SoundsCfg)`.
    - Per syllable it returns None (not checked) or `{"status": "ok"|"slip", "heard": str|None, "heard_pinyin": str|None, "z": float, "rule": "fused"|"b_only"}`.
    - `heard` and `heard_pinyin` are set only on a slip: `heard` = B's argmax partner on the take, `heard_pinyin = heard_pinyin(heard, syllable["tone"])`.
    - It caches the reference's B GOPs per `ref_key` (the clip path plus text), keeping the last 64.
  - `class FakeSounds(Sounds)`, `FakeSounds(results: list[dict | None] | None = None, error: bool = False)`: returns the given list, or raises when `error`. For scoring tests.

Algorithm (spike `method_a.py` / `method_b.py`, abs/delta as in `evaluate.badness`):
1. Take the expected toneless syllables: `[s["pinyin_toneless"].lower() for s in syllables]`.
2. Work out which syllables can be checked. A syllable is skipped (None) when any of these holds:
   - `statuses[i]` is `missing` or `unvoiced`
   - `syllables[i]["tone"] < 0`
   - it is not in `inventory()`
3. **A (letters).**
   - `seqA = [letter_ids(s)]`.
   - The A alternatives of syllable i are the distinct `letter_ids(p)` over `partners(s)`, dropping any equal to `seqA[i]`.
   - `bad_a = −win_gop(emissions(take), blank, seqA[i], altsA[i], usr_win[i], frame_s)`. None without A alternatives.
4. **B (characters).**
   - `seqB = [[sid(s) or 0] for s in syl]`.
   - The B alternatives of syllable i are `[[sid(p)]]` for the partners p that have a `sid`.
   - Take `utt_gops` on `group_logp(take)` (usr) and on `group_logp(ref_wav)` (ref; cached).
   - `bad_b = gop_ref − gop_usr` when both exist, else None.
   - Heard on the take = the argmax alt's syllable.
5. `decide(bad_a, bad_b, cfg)`; None stays None.

- [ ] **Step 1: Write the failing tests**, with fake `LetterModel` and `CharModel` classes whose matrices spell a chosen syllable sequence, as in Task 2:
  - `test_check_marks_a_slip_and_names_what_was_heard`: expected `["ta", "chi"]`. The take's matrices spell `ci`; the reference spells `chi`. Assert `out[1]["status"] == "slip"`, `out[1]["heard"] == "ci"`, `out[1]["heard_pinyin"] == "cī"` (tone 1), and `out[0] is None` (`ta` has no partner).
  - `test_check_ok_when_take_matches_reference`: the take spells `chi`; assert `out[1]["status"] == "ok"` and `out[1]["heard"] is None`.
  - `test_check_skips_unjudgeable_syllables`: syllables 儿 `er` (tone 2), a `missing` status, a tone −1 character, and `ding` (A partner only, since `din` has no B group). Assert all None, with no exception.
  - `test_reference_gops_are_cached`: a fake `CharModel` counts `group_logp` calls. Two `check`s with the same `ref_key` run the reference once.
- [ ] **Step 2: Run them and see them fail**
- [ ] **Step 3: Implement** `align.py` additions and `detector.py`
- [ ] **Step 4: Run them and see them pass**, plus the whole backend suite (`tests/test_align.py` must stay green)
- [ ] **Step 5: Commit** `feat(sounds): per-take detector over MMS letters and char-CTC`

---

### Task 6: Check-set regression test (models), the parity gate

**Files:**
- Create: `backend/tests/test_sounds_real.py` (`pytestmark = pytest.mark.models`)

**Interfaces:**
- Consumes: `SoundDetector`, `CharCtc`, `MmsAligner`, `trim_silence`, `windows`, `segment_syllables`, `reference_audio`.

The test is `test_check_set_parity`:
1. Skip unless `data/shadow.db`, `data/reports/phase3-checkset.json` and `data/reports/phase3-checkset.record_after` exist (repo root `data/`).
2. Open the DB read-only (`file:...?mode=ro`).
3. For each check-set item without `"excluded"`, take the newest two attempts of its `segment_id` that were created after `record_after` (normalise the timestamp to `YYYY-MM-DD HH:MM:SS`) and have a score with an empty `warnings`. Order them oldest first: normal, then slip.
4. For each take:
   - read the WAV and `trim_silence` it
   - `MmsAligner.align` it on the segment text
   - `windows()` over the spans
   - `statuses` = the stored `score_json` syllable statuses
   - call `check(...)` with the segment clip as the reference
5. Normalise the check-set pinyin `ü` → `v`.
6. Assert:
   - slips marked at `syl_index` ≥ 22 of 29
   - marked syllables over all normal-take syllables ≤ 0.06
   - every marked slip's `heard` equals `slipped_pinyin_toneless`
7. Print the counts. The spike got 23/29 and 3.9 %.

- [ ] **Step 1: Write the test**
- [ ] **Step 2: Run it (controller; the user stops the backend first for RAM)**: `cd backend && OMP_NUM_THREADS=4 ~/.local/bin/uv run pytest -q -s -m models tests/test_sounds_real.py`. Expected: PASS, with the printout close to 23/29 and 3.9 %.
  - If it fails, compare against the spike before changing anything. The spike's per-item values are in `.superpowers/sdd/p3a-spike/results_check.md` and its score JSONs. Fix the port, not the thresholds.
- [ ] **Step 3: Commit** `test(sounds): check-set parity with the 3a spike`

---

### Task 7: Scoring, storage, deps and health

**Files:**
- Modify:
  - `backend/shadow/store/models.py`: `SyllableScore.sound_status: str | None = None` (`ok|slip`) and `heard_syllable: str | None = None`. `seg_score` holds the decision's z.
  - `backend/shadow/scoring/score.py`
  - `backend/shadow/scoring/__init__.py`
  - `backend/shadow/deps.py`
  - `backend/shadow/main.py`
  - `backend/shadow/api/health.py`
- Test: `backend/tests/test_score.py`, `backend/tests/test_scoring_api.py`, `backend/tests/test_health.py`

**Interfaces:**
- Consumes: `Sounds`, `FakeSounds`, `SoundDetector`, `CharCtc` (Tasks 4–5).
- Produces:
  - `score_take(..., sounds: Sounds | None = None, ref_key: str = "")`:
    1. After the tone loop it calls `sounds.check` with `take=trimmed`, `usr_win`, `ref.wav/ref.sr`, the syllables and the statuses in `out_syl`.
    2. It sets each syllable JSON's `sound` (default `None` in `_syl_json`; `failed_result` keeps it None).
    3. It sets the row's `sound_status`, `heard_syllable` and `seg_score` (= z).
    4. Top level: `sounds_off` = the number of slips; `sounds_checked` = the number of non-None results.
    5. Without `sounds`, or when `check` raises (log it), both are `None` and every `sound` is None.
  - `failed_result` adds `"sounds_off": None, "sounds_checked": None`.
  - `score_attempt` passes `deps.sounds` and `ref_key=f"{segment.clip_wav_path}|{segment.text}"`.
  - `Deps.sounds: Sounds | None = None` and `Deps.sounds_error: str | None = None`. In `build_deps`, when `settings.sounds.enabled`:
    - If the aligner's inner model is an `MmsAligner`: `SoundDetector(aligner, CharCtc(cfg.model, cfg.revision, device), cfg)`.
    - Otherwise `sounds_error = "sounds need the MMS aligner"`.
  - `loaded_models()` adds `"sounds"` when the `CharCtc._model` is loaded.
  - The lifespan warms `CharCtc` like the embedder (real deps only). A failed warm-up sets `deps.sounds_error` to the exception text.
  - `/health` adds `"sounds_error": deps.sounds_error`.

- [ ] **Step 1: Write the failing tests**
  - In `test_score.py`, with the existing fake setup:
    - `test_score_take_stores_sound_results`: `FakeSounds` returns a slip at index 1 and ok at index 0. Assert:
      - `json["syllables"][1]["sound"]["heard_pinyin"]` is set
      - `json["sounds_off"] == 1` and `json["sounds_checked"] == 2`
      - row 1 has `sound_status == "slip"` and `heard_syllable` set
      - `overall` equals the same take scored without `sounds`
    - `test_sound_failure_keeps_tone_score`: `FakeSounds(error=True)` gives the same `overall` as no sounds, with `sounds_off is None` and every `sound is None`.
  - `test_scoring_api.py`: posting an attempt with `deps.sounds = FakeSounds([...])` stores the columns.
  - `test_health.py`: `sounds_error` is present.
- [ ] **Step 2: Run them and see them fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the whole backend suite and see it pass**
- [ ] **Step 5: Commit** `feat(sounds): score, store and serve sound results`

---

### Task 8: Back-fill of existing takes

**Files:**
- Create: `backend/shadow/scoring/sounds/backfill.py`, `backend/scripts/backfill_sounds.py`
- Modify: `Makefile` (target `backfill-sounds`)
- Test: `backend/tests/test_sound_backfill.py`

**Interfaces:**
- Produces `backfill_attempt(deps: Deps, db: Session, attempt: Attempt) -> bool`. It returns False (and changes nothing) unless all of these hold: `overall` is not null, `deps.sounds` is set, and the take's audio exists.
- It recomputes the take side exactly as `score_take` does: `trim_silence`, `deps.aligner.align`, then `windows`. It then calls `deps.sounds.check` with statuses from the stored syllables.
- It updates only:
  - each syllable's `sound` in `score_json`
  - `sounds_off` and `sounds_checked`
  - the attempt's `SyllableScore` rows' `sound_status`, `heard_syllable` and `seg_score`, matched by `idx`
- Call `flag_modified(attempt, "score_json")`. Never touch tone fields or `overall`.
- If the alignment count no longer matches, skip the attempt and return False.
- The script runs over all attempts oldest first, commits every 20, and prints counts (done, skipped, slips).
- The Makefile target `backfill-sounds` runs it.

- [ ] **Step 1: Write the failing tests**
  - `test_backfill_writes_only_sound_fields`: snapshot `overall`, `tone_score`, `status` and `target_tone` before; run with `FakeSounds`; assert those are unchanged, the sound fields are set, and a second run is idempotent.
  - `test_backfill_skips_unscored_attempts`: an attempt with `overall: null` returns False.
- [ ] **Step 2: Run them and see them fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run them and see them pass**
- [ ] **Step 5: Commit** `feat(sounds): back-fill sound results for existing takes`

The real run happens in Task 13.

---

### Task 9: Stats `/stats/sounds` and the `sound` drill focus

**Files:**
- Modify:
  - `backend/shadow/api/stats.py`
  - `backend/shadow/drill/queue.py`
  - `backend/shadow/drill/summary.py`
  - `backend/shadow/drill/focus.py` (`focus_label` for `sound` → `drill_label(key)`)
  - `backend/shadow/api/drill.py` (`_valid`: `kind == "sound" and key in DIRECTIONS`)
- Test: `backend/tests/test_stats_api.py`, `backend/tests/test_drill_queue.py`, `backend/tests/test_drill_api.py`

**Interfaces:**
- Produces:
  - **`GET /stats/sounds`** → `{"sounds": [{key, label, slips, chances, rate}], "weeks": [{week, key, rate, slips, chances}]}`.
    - Rows are `SyllableScore` rows with `sound_status IS NOT NULL`.
    - A row is a chance for every direction in `directions_of(pinyin_toneless)`.
    - It is a slip for `direction(pinyin_toneless, heard_syllable)` when `sound_status == "slip"`.
    - `sounds` lists directions with chances ≥ 8, sorted by rate descending (ties: more chances first). `label = direction_label(key)`.
    - `weeks` covers the last 12 ISO weeks (same `since` as `/stats/tones`), joined to `Attempt.created_at`, and includes only directions present in `sounds`.
  - **Drill targets.** `targets_for(syllables, "sound", key)` = the indexes i with `key in directions_of(syllables[i]["pinyin_toneless"].lower())`.
  - **Green.** `went_green(db, ds_id, segment_id, targets, kind="tone")`: for `kind == "sound"` every target row needs `sound_status == "ok"`. A NULL counts as not ok. `_recent_green` passes `ds.kind`.
  - **Summary.**
    - `target_mean` gains `kind`. For `sound`, rows map idx → `sound_status`; mean = (targets ok) / (number of targets); green = targets ok. Unchecked targets count in the denominator.
    - `_takes` selects `SyllableScore.sound_status` for sound sessions.
    - `went_green` in `_totals` is unchanged (`green == len(targets)`).
  - `GET /drill/focuses` is unchanged: no sound focuses in the auto pick.

- [ ] **Step 1: Write the failing tests**
  - `test_stats_sounds_rates_by_direction`, built from inserted rows: 10 `chi` rows (2 slip heard `ci`, 8 ok) and 5 `ping` rows. Assert `ch>c` has slips 2, chances 10, rate 0.2, label "ch said as c", and that `ng>n` is absent (5 < 8).
  - `test_sound_targets`: `targets_for` on 她喜欢吃苹果 with key `ch>c` is `[3]`; with `ng>n` it is `[4]`.
  - `test_sound_green_needs_every_target_checked_ok`: the targets have `ok` and NULL, so not green; with all `ok`, green.
  - `test_create_sound_drill`: `POST /drill/sessions {"kind":"sound","key":"ch>c"}` gives 201 with label "ch (not c)"; key `"x>y"` gives 400.
  - `test_sound_summary_mean_is_share_ok`.
- [ ] **Step 2: Run them and see them fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the whole backend suite and see it pass**
- [ ] **Step 5: Commit** `feat(sounds): Sounds stats and sound drill focus`

---

### Task 10: Frontend types and sound-aware drill green

**Files:**
- Modify: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`, `frontend/src/lib/drill.ts` (+ `drill.test.ts`), `frontend/src/components/DrillRunner.tsx`

**Interfaces:**
- Produces:
  - `SoundResult = { status: 'ok' | 'slip'; heard: string | null; heard_pinyin: string | null; z: number; rule: 'fused' | 'b_only' }`
  - `ScoredSyllable.sound?: SoundResult | null`
  - `Score.sounds_off?: number | null` and `Score.sounds_checked?: number | null`
  - `DrillFocus.kind` adds `'sound'`
  - `SoundStats = { sounds: { key: string; label: string; slips: number; chances: number; rate: number }[]; weeks: { week: string; key: string; rate: number; slips: number; chances: number }[] }`
  - `api.stats.sounds()` → `/stats/sounds`
  - `targetsGreen(score, targets, kind = 'tone')`: for `'sound'`, every `score.syllables[t]?.sound?.status === 'ok'`. `overall == null` stays false.
  - DrillRunner passes `session.kind`.

- [ ] **Step 1: Write the failing tests** in `drill.test.ts`:
  - `'sound kind needs every target sound ok'`: tone statuses all `ok` but one target's `sound` is `null` gives false; all `sound.status==='ok'` gives true even with `status: 'wrong'`.
- [ ] **Step 2: Run them and see them fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the frontend checks**: `npm test -- --run && npx eslint . && npx tsc -b`
- [ ] **Step 5: Commit** `feat(sounds): frontend types, sound drill green`

---

### Task 11: Feedback block: HEARD row, purple rings, header chip, click your syllable

**Files:**
- Modify:
  - `frontend/tailwind.config.ts`: `sound: '#c678dd'`
  - `src/lib/cells.ts`: `Cell.heardSound?: string | null`
  - `src/lib/score.ts`: `withScore` sets `heardSound` from `sound?.status === 'slip' ? sound.heard_pinyin : null`
  - `src/components/CellRow.tsx`: new prop `soundMarks?: number[]` gives `ring-2 ring-sound`; the `you` variant also calls `onCellClick`
  - `src/components/TwoTrack.tsx`
  - `src/components/ScoreHeader.tsx`
  - `src/pages/Practice.tsx` and `src/components/DrillRunner.tsx`: `playYouSyllable`
- Create: `src/components/HeardRow.tsx`
- Test: `src/components/HeardRow.test.tsx`, `TwoTrack.test.tsx`, `ScoreHeader.test.tsx`, `CellRow.test.tsx`, `src/pages/Practice.test.tsx`

**Interfaces:**
- Produces:
  - **`HeardRow({ cells }: { cells: Cell[] })`**
    - Renders nothing when no cell has `heardSound`.
    - Otherwise renders a `HEARD` label, then one slot per cell at the CellRow cell width and gap, so it aligns.
    - Slots with `heardSound` show it in `text-sound font-semibold`, with a dashed `border-sound` outline and `title="heard {heardSound} instead of {pinyin}"`. Other slots are empty.
  - **TwoTrack**
    - Gains the optional prop `onPlayYouSyllable?: (i: number) => void`.
    - Passes `soundMarks` (the indexes of You cells with `heardSound`) to the **reference** CellRow.
    - Renders `<HeardRow>` under the You CellRow.
  - **ScoreHeader** replaces the `segmental · Phase 3` chip:
    - `sounds_off ≥ 1`: `"{n} sound(s) off"` in `text-sound`
    - `sounds_off === 0 && (sounds_checked ?? 0) > 0`: `"sounds ok"`
    - otherwise: no chip
  - **Your syllable playback.** `playYouSyllable(i)` plays `score.usr_contour.spans[i]` of the current take's URL via `player.playRange(url, 1, from, to, setYouHead)`. Those spans are already on the raw take's timeline (spec §1.2). There is no span when the cell is `missing`/`unvoiced` or there is no score.
    - In Practice, the take is `currentTake(usePractice.getState())`. Wrap the call in `playSolo` as `replayYou` does.
    - In DrillRunner, the take is `takeRef.current`, called through the local `playSolo(url, setYouHead, from, to)`.

- [ ] **Step 1: Write the failing tests**
  - `HeardRow.test.tsx`:
    - `'shows only the slipped syllables, aligned'`: cells 她喜欢吃苹果 with `heardSound` on 3 (`cī`) and 4 (`pín`) render exactly two texts, `cī` and `pín`, in slots 3 and 4 of 6.
    - `'renders nothing without slips'`.
  - `TwoTrack.test.tsx`:
    - `'rings the reference cells above heard sounds'`
    - `'renders as before without sound fields'`: a score whose syllables lack `sound` gives no `HEARD`, no ring, and the same cell texts as today.
    - `'clicking a You cell calls onPlayYouSyllable(i)'`
  - `ScoreHeader.test.tsx`: the three chip states, including old scores without the fields, which show no chip.
  - `Practice.test.tsx`: clicking a You cell plays the take's URL from `usr_contour.spans[i][0]` to `[1]`.
- [ ] **Step 2: Run them and see them fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the frontend checks**
- [ ] **Step 5: Commit** `feat(sounds): HEARD row, sound rings, header chip, play your syllable`

---

### Task 12: Stats Sounds panel

**Files:**
- Create: `frontend/src/components/SoundsPanel.tsx` (+ test)
- Modify: `frontend/src/pages/Stats.tsx` (+ `Stats.test.tsx`)

**Interfaces:**
- Consumes: `api.stats.sounds()` and `SoundStats` (Task 10).
- Produces `SoundsPanel({ stats, onDrill }: { stats: SoundStats; onDrill: (key: string) => void })`.
  - One row per entry: label, `"{slips} of {chances}"`, rate as a percentage, and a small trend for that key (the weekly rates as an inline sparkline, or arrows as the Characters panel does; builder's choice).
  - A `Drill this` button with `aria-label="Drill {label}"`.
  - Empty state: "No sound results yet."
- Stats loads `api.stats.sounds()` alongside the others. It renders the `<Panel title="Sounds">` after Tones and wires `onDrill` to `drill('sound', key)` (the existing `encodeURIComponent` keeps `>` safe).

- [ ] **Step 1: Write the failing tests**
  - `SoundsPanel.test.tsx`: renders "ch said as c" and "2 of 10"; clicking Drill calls `onDrill('ch>c')`.
  - `Stats.test.tsx`: Drill this navigates to `/drill?kind=sound&key=ch%3Ec`.
- [ ] **Step 2: Run them and see them fail**
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run the frontend checks**
- [ ] **Step 5: Commit** `feat(sounds): Stats Sounds panel with Drill this`

---

### Task 13: Docs, acceptance checklist, back-fill run

**Files:**
- Modify: `README.MD` (Phase 3a in the feature list and layout table; the `backfill-sounds` target)
- Create: `docs/phase3a-acceptance.md`

The acceptance checklist must include:
1. Say 吃 as cī in Echo. The HEARD row shows `cī` under 吃, 吃 is ringed in the reference row, and the chip reads "1 sound off".
2. A clean take shows no HEARD row and the chip reads "sounds ok".
3. Clicking a You cell plays that syllable.
4. Stats shows a Sounds panel. Drill this starts a sound drill whose item goes green when the sound is right, even if a tone is orange.
5. `/health` lists `sounds`, and `sounds_error` is null.
6. VRAM and RAM stay usable while gaming.

- [ ] **Step 1: Write the docs**
- [ ] **Step 2: Back-fill (controller, with the user's go-ahead; it writes the DB)**
  1. Back up: `cp data/shadow.db data/shadow.db.bak-before-sounds-$(date +%F)`.
  2. Have the user stop the backend.
  3. Run `make backfill-sounds`.
  4. Expected: every scored take is done or explicitly skipped, and the slip count is plausible (a few % of checked syllables).
- [ ] **Step 3: Run the full suites one last time** (backend, frontend, then the models test from Task 6)
- [ ] **Step 4: Commit** `docs: Phase 3a sounds in README and acceptance checklist`
