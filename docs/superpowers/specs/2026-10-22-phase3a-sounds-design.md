# Phase 3a — Wrong-sound detection

Addendum to `2026-10-03-shadowing-tool-design.md` (main spec),
`2026-10-09-phase2-tone-scoring-design.md` (Phase 2) and
`2026-10-14-phase3b-drills-design.md` (3b drills). Agreed with the user on
2026-10-21/22. The detection method comes from the 3a spike
(`.superpowers/sdd/p3a-spike/`, git-ignored; `RESULTS.md` there has all
numbers and the "Check set" section has the go verdict).

## 0. Intent

**What the user asked for.** After a take, **mark the syllables whose sound was
wrong and show what was heard**, e.g. 吃 should be chī, the app heard cī. Make
"should say" and "you said" unmistakable. Clicking one of **your** syllables
plays just that syllable from your take, the same as clicking a reference
syllable does today, so the two can be compared by ear. Sound slips then go
**the same way as tone slips**: into Stats, with **Drill this**, and into
Drills.

**Why.** Phase 2 tells the user when a tone is off, but not when he says c for
ch, -n for -ng, or u for ü. Those are the slips a learner can't hear in his
own speech.

**Success.**
- After a take, a wrong ch/c, -n/-ng and similar slip is marked with what was
  heard.
- False marks are rare enough to trust the marks: about 1 in 25 correct
  syllables on the user's speech.
- Stats shows which sounds he slips on most.
- A sound drill makes the marks go away.

**Anti-goals.**
- Purple marks that cry wolf. Thresholds must not be loosened to catch more.
- Marks mixed up with the tone colours.
- Tone scoring changed or slowed down noticeably.

**Not in scope.**
- Articulation tips ("curl the tongue back").
- Sound slips lowering the sentence score.
- Sounds in the automatic drill pick.
- Sounds in the Flow summary or the Anki export.
- Checking syllables without a confusable partner (see §2.3).

## 1. What the user sees

### 1.1 Feedback block (TwoTrack), option "E" chosen in the mockups

- **HEARD row.** Under the You cells, a row labelled `HEARD` shows a syllable
  only where its sound was marked wrong. It shows the heard syllable as pinyin
  with **the same tone mark as the reference cell above it**, i.e. the
  dictionary tone from `words_json` (`cī` under `chī`, `pín` under `píng`), so
  only the sound differs between the two rows. Do not use `target_tone`: it
  differs from the dictionary tone on ~15 % of syllables (sandhi, e.g. 很 hén)
  and would make a sound slip look like a tone slip. Neutral tone → no mark.
  *My call.* It appears in purple
  with a dashed purple outline, aligned under its cell. Every other position
  is empty.
- **Reference ring.** The reference cell directly above a marked syllable gets
  a purple ring, so what the user should say (the reference row's pinyin) and
  what was heard sit one above the other.
- **No marks, no row.** When nothing is marked, or nothing could be checked,
  the row is not rendered and the block looks exactly as today.
- **Purple means sound only.** Cell colours (green, orange, red, grey) keep
  meaning tone. Purple is used for nothing else. The exact purple is the
  builder's choice; the mockup used `#c678dd` on the dark theme.
- **Header chip.** The placeholder chip `segmental · Phase 3` in `ScoreHeader`
  becomes `N sound(s) off` when N ≥ 1, or `sounds ok` when at least one
  syllable was checked and none was marked. The chip is hidden when no
  syllable was checked or sound checking is unavailable.
- **Sentence score unchanged.** `overall` stays the Phase 2 tone score.

### 1.2 Click your own syllable

The You cells become clickable: clicking cell *i* plays syllable *i*'s span
from the user's take. This works for every scored take, not only marked
syllables, and for tone slips too. It mirrors the reference row
(`onPlaySyllable`). The spans are the learner alignment already in
`score_json.usr_contour.spans`. The builder must check which audio those
spans are already shifted onto the raw take's timeline (`+ off` in
`score.py`), so they index the stored take directly. Missing or unvoiced
cells play nothing.

### 1.3 Where it appears

The feedback block appears wherever `TwoTrack` renders a scored take:
Practice (Echo / Chorus) and the Drill page. Nothing else changes in Flow mode.

## 2. Detection

### 2.1 Method (from the spike, unchanged)

The pre-registered spike candidate is **z-sum of A.win (abs) + B.utt
(delta)**. It is computed per syllable *i* of the expected text, on the
trimmed take the scorer already uses, with the take alignment and windows
Phase 2 already computes. "Partners" of the expected toneless syllable are
defined in §2.3.

- **A, MMS letters, windowed, learner only.**
  - Use the app's MMS_FA model (`MmsAligner`, `with_star=False`), so no new
    model is needed. Take the frame log-probs over the take and the letter
    spelling `romanise_for_mms`, in which ü is written as u.
  - Take the frames of syllable *i*'s window (`windows()` with the app's
    rules). Widen the window by one frame each side until it has enough frames
    for the longest candidate's CTC path.
  - `GOP_A = ll_CTC(expected letters) − max over partners ll_CTC(partner letters)`.
  - Partners whose letter spelling equals the expected one are dropped (for
    example nü/nu and lü/lu).
  - `bad_A = −GOP_A`.
- **B, char-CTC, full utterance, reference-relative.**
  - Model: `wbbbbb/wav2vec2-large-chinese-zh-cn` at revision
    `b654b5f3df69725df32808de454a1b865c829e4c` (Apache-2.0). It is already
    named in `ModelsCfg.gop_model`.
  - Normalise the waveform to zero mean and unit variance, run the model, and
    take the softmax over its character vocabulary.
  - Sum the character posteriors into **toneless-syllable groups**: a
    character counts for every reading `pypinyin` gives it (`heteronym=True`,
    ü → v). Blank is its own group.
  - The groups cover the syllable inventory of the spike's
    `valid_syllables.json`, which is AISHELL-3 train+test toneless
    syllables. Freeze that list into the repo next to the model config.
  - `GOP_B(i) = ll_CTC(whole expected syllable sequence) − max over partners
    ll_CTC(sequence with syllable i swapped for the partner)`, where ll_CTC is
    the full-utterance CTC log-likelihood over group log-probs.
  - Compute it on the take (`GOP_B_usr`) and on the segment's reference clip
    (`GOP_B_ref`; the clip result can be cached per segment).
  - `bad_B = GOP_B_ref − GOP_B_usr`.
- **Fusion.** z-normalise each value with constants from the spike's 200
  control splices, then add:
  - `z_A = (bad_A − (−4.006537)) / 2.974512`
  - `z_B = (bad_B − 1.239741) / 3.072057`
  - The syllable is **marked** when `z_A + z_B > 5.3036` (the threshold set
    at 5 % false marks on the user's old clean takes, frozen 2026-10-14).
- **Only B has a partner** (lü/lu, nü/nu, where A cannot hear ü). Mark when
  `bad_B > 11.6518`, which is B.utt (delta)'s frozen 5 %-clean-takes
  threshold. *Builder's rule, not validated as a fusion.* On check-set item
  21 (nǚ→nǔ) it marks the slip and not the normal take.
- **Only A has a partner** (a partner with no characters in B's vocabulary,
  e.g. ding/din): not checked, as in the spike. *My call.*
- **Not checked.** A syllable with no partner in either model is not
  checked. Neither is a syllable whose reference GOP or take GOP cannot be
  computed (missing or unvoiced syllable, take failed the gates).

### 2.2 What was heard

For a marked syllable, the heard syllable is the partner with the highest B
full-utterance likelihood (the argmax inside `GOP_B_usr`). On the check set
this was the syllable the user actually said in 29/29 slips, and A agreed 29/29.

### 2.3 Contrasts and partners

Partners of a toneless syllable are every syllable that differs by one of
these contrasts **and** is in the syllable inventory. Both directions count.
This is `common.partners()` in the spike.

| Contrast | Partner pairs |
|---|---|
| initials | zh/z, ch/c, sh/s, r/l, f/h |
| -n/-ng | an/ang, en/eng, in/ing, ian/iang, uan/uang |
| ü/u | lü/lu, nü/nu, yu/wu (whole syllable) |
| vowels | ai/ei, ao/ou, ou/uo, an/en, ang/eng |

A syllable with no partner, such as wo, de or jia, is never checked. That was
157 of 376 syllables in the user's old takes.

### 2.4 Validated performance (what to expect)

- **Check set, held out** (29 planned slips, the user, 2026-10-21): 23/29 caught
  (79 %), 3.9 % false marks on the syllables of his normal takes, and 2.8 % on
  the other syllables of the slip takes.
- **Native splices** (AISHELL-3): 59 % caught at this threshold, and 0.0 %
  false marks on native speakers.
- **Weakest contrasts:** -n/-ng (in↔ing missed twice), then zh/z and sh/s on
  在 and 睡.
- **Rejected alternatives:**
  - Using the user's own normal take as the reference: no better.
  - Paraformer: not a detector.

## 3. Data

- **`SyllableScore`** gains:
  - `sound_status`: `ok | slip | NULL`, where NULL means not checked.
  - `heard_syllable`: the toneless heard partner, or NULL.
  - `sound_z`: the fused value used for the decision, for later threshold
    work. For B-only syllables, store `z_B` and record which rule applied in
    `score_json`.
  - The existing unused `seg_score` column may hold `sound_z` instead of a new
    column. That is the builder's call.
- **`score_json`**, per syllable: `sound: {status, heard, heard_pinyin, z,
  rule} | null`, where `heard_pinyin` is the tone-marked string the UI shows.
  Top level:
  - `sounds_off`: the count of slips.
  - `sounds_checked`: the count of checked syllables.
  - `segmental_overall` stays `null`. It is not a score.
- **TS types:** `ScoredSyllable.sound` and `Score.sounds_off` /
  `sounds_checked`.
- **Back-fill.** A one-off script adds sound results to every existing scored
  attempt. It writes only the new fields and leaves tone results and
  `overall` untouched, which is why it does not reuse `rescore.py`, a full
  rescore. It is idempotent and safe to rerun after a threshold change.

## 4. Stats: Sounds panel

- **Grain: one row per contrast direction.** The key is
  `"<expected part>><heard part>"`, for example `ch>c` (should be ch, heard
  c), `ng>n` (should be -ng, heard -n), `ü>u`, `ou>uo`.
  - A checked syllable is a **chance** for a direction when one of its
    partners differs from it in exactly that way.
  - It is a **slip** for that direction when it was marked and the heard
    partner is that one.
  - The **slip rate** is slips / chances.
  - The mapping from (expected, heard) to a direction label is a small pure
    function. Its labels are the builder's choice within this scheme.
- **Rows:** label (e.g. "ch said as c"), slips / chances, rate, and a trend
  (weekly rate over the last 12 ISO weeks, like ToneTrend). Rows are sorted
  by rate, highest first. A direction shows only with at least 8 chances.
  Like the other Stats panels, the panel covers all time.
- **Drill this** on every row → `/drill?kind=sound&key=ch>c`.
- **Endpoint:** `GET /stats/sounds` → `{sounds: [{key, label, slips, chances,
  rate}], weeks: [...]}`.

## 5. Drills: `sound` focus

This fills the slot 3b reserved, with key = a contrast direction from §4.

- **Targets.** In a candidate sentence, the target syllables are those that
  are a chance for that direction (§4), found from `words_json` syllables.
- **Queue.** Same rules as 3b §2, with "contains a target" meaning the above.
- **Done for an item.** Every target syllable has `sound.status == "ok"`. Tone
  status does not count for a sound drill; tone colours still show.
  - A target that could not be checked in a take counts as not ok for that
    take. A gated take still costs no try.
  - Apply this in both `went_green()` (backend) and `targetsGreen()`
    (frontend), selected by the session's kind.
- **Summary.** For a sound drill, the per-item and session "mean" is the
  share of target syllables with sound ok (0–1), and "green" is the count of
  targets ok. The history line uses the same measure.
- **Auto pick.** Unchanged. `GET /drill/focuses` does not return sound
  focuses, and sounds start only from Stats or a URL. `_valid` accepts
  `kind = sound` with a known direction key.
- **Label.** E.g. "ch (not c)".

## 6. Model loading and cost

- **B is the only new model.**
  - It adds ≈ 1.2 GB GPU weights, with a peak ≈ +1.4 GB in fp32.
  - Per take it costs ≈ 30 ms forward + 20 ms scoring on the RTX 3070, plus
    one forward per reference clip (cacheable).
  - A costs ≈ 15 ms extra on the already-loaded MMS model.
- **Constraints.**
  - Same PC as the user's games: 8 GB VRAM and 7.7 GB RAM visible to WSL.
  - The running backend already holds ≈ 5.3 GB RSS.
  - Loading B must not push the box into swap or out of memory. Load it
    straight to the GPU in the way that keeps the CPU-side peak small, and
    warm it up in the lifespan hook like the embedder and ASR.
  - `/health` lists it among the loaded models.
- **Measure before wiring it in.** First task of the plan: load B in the
  running backend (after the existing warm-up) and measure RSS, available RAM
  and VRAM. If it does not fit without swapping, stop and bring the numbers
  back to the user rather than choosing a fallback (lazy load, default off,
  dropping another model). *My call.*
- **fp32, as validated.** fp16 is allowed only if the check-set regression
  test (§9) still passes unchanged.
- **CPU fallback.** Runs as the rest of the app does.

## 7. Config

`[sounds]` in `config.toml`:
- `enabled = true`
- `z_a_mean`, `z_a_sd`, `z_b_mean`, `z_b_sd`, `fused_threshold = 5.3036`,
  `b_only_threshold = 11.6518`
- the model id and revision

The syllable inventory file lives alongside the config.

## 8. Errors and degradation

- **B fails to load** (out of memory, missing weights): tone scoring works
  exactly as before, every `sound` is null, the header chip is hidden, and
  `/health` says why.
- **Any exception inside sound scoring** must not fail the take. Sounds are
  null for that take, and tone results are stored as normal.

## 9. Testing

- **Unit tests:**
  - partners and contrast directions
  - direction mapping
  - the fusion decision and the B-only rule on synthetic GOPs
  - heard argmax
  - stats aggregation: chances, slips, min 8, weeks
  - sound focus: targets, queue, green rule, summary measure, `_valid`
  - back-fill leaves tone fields untouched
- **Model test** (`-m models`), a check-set regression:
  - Run the real detector on the user's 29 check-set pairs. The attempt ids are
    in the spike's `items_check.json`; pairs are the newest two takes per
    segment after `data/reports/phase3-checkset.record_after`.
  - Assert ≥ 22/29 slips marked, ≤ 6 % false marks over **all** syllables of
    the normal takes (the spike's denominator, not only checked ones), and the heard syllable equals the planned slip on every marked
    slip.
  - This guards parity with the spike: 23/29 and 3.9 %.
- **Frontend tests:**
  - the HEARD row renders only marked syllables, aligned
  - the reference ring
  - no row when nothing is marked
  - the header chip states
  - clicking a You cell plays that syllable's span
  - the Stats Sounds panel and Drill this
  - a sound drill's green and retry behaviour

## 10. Left to the builder

- Code layout: a new module under `backend/shadow/scoring/`.
- Caching reference-clip results.
- How the CTC sums are batched.
- The exact purple and the row styling within §1.1.
- Direction labels.
- Whether `sound_z` uses the existing `seg_score` column.
