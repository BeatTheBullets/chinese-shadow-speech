# Phase 2 — Tone scoring

Addendum to `2026-10-03-shadowing-tool-design.md` (the "main spec") and
`2026-10-07-youtube-passages-guidance-design.md`. Where they disagree, this
document wins for the topics it covers; it replaces main spec §5.2 and the
"Phase 2 notebook" calibration. Agreed with the user on 2026-10-09.

## 0. Intent

**What the user said.** Tone is not a matter of taste: a listener gets used to a
speaker's voice and hears each tone as a movement relative to that voice's
baseline. Shadowing makes this easier still, because the original speaker
shows how the pitch should move at each character relative to *their*
baseline; the learner's movement relative to *their own* baseline (measured
over a Flow run and beyond) can be compared with it. The app must be useful
for anyone, without a tone-labelled dataset of the learner's own voice; an
open dataset may train the classifier.

**Approach (C, agreed).** Two signals per syllable:

- a **tone classifier**, trained once offline on the open native corpus
  AISHELL-3 and shipped in the repo, decides *which tone category* was
  produced — the categorical judgement a native listener makes. It sets the
  cell colour and the "you said 2" feedback;
- **contour similarity** (DTW of the speaker-normalised pitch curves, learner
  against reference) gives the fine score that rises as the learner gets
  closer, and drives the overlay.

Both use pitch normalised to each speaker's own baseline: the reference
speaker over the whole lesson, the learner over a running voice profile.

**Success.** After a take, every syllable shows a colour that matches what a
native would hear (green right tone, orange unsure, red a different tone with
the heard tone shown), a 0–100 score, and the two pitch curves; a reopened
lesson shows the same; Stats shows per-tone means over time, a tone-pair
matrix and the weakest characters. Nobody labels anything.

**Not in scope.** Segmental (GOP) scoring (Phase 3); per-user accounts (the
voice profile is one per installation, resettable); retraining from the
learner's takes; a deliberate-error calibration session.

## 1. Scoring one take

Runs inside `score_attempt` (synchronously, in the upload request, as now).
Each Flow slice is already its own attempt.

1. **Trim** leading and trailing silence (energy-based, keeps 50 ms) — the
   main spec §6.1 slack deferred in Phase 1.
2. **Quality gate.** Every syllable `missing`, `tone_overall` null and a
   warning, when:
   - the trimmed take is shorter than `min_duration_ratio` (0.4) × the
     reference speech span → `too_short`;
   - its RMS level is below `min_rms_dbfs` → `too_quiet`;
   - more than 1 % of samples are clipped → `clipped`;
   - **words check** (after the checks above, before alignment): the take is
     transcribed with the ingest recogniser (Paraformer; the instance is
     shared with ingest jobs and calls are serialised with a lock) and
     compared with the sentence in toneless pinyin: Levenshtein normalised
     similarity over syllable lists, non-hanzi skipped on both sides. When
     the transcript contains Latin letters (a name written in English, e.g.
     丽丽 heard as "lily"), a letter-level similarity of the concatenated
     toneless pinyin (Latin words kept, lower-cased) is also computed and the
     higher one counts. Three bands: below `min_text_similarity` (0.25) →
     `different_words`, not scored; from there to `words_ok_at` (0.55) the
     take is tone-scored as usual and the score JSON gets
     `notices: ["words_differ"]` (`warnings` stays empty, so "warnings ⇒ not
     scored" holds); from `words_ok_at` on, no notice. Toneless on purpose: a
     wrong tone can make the recogniser write a homophone, which is a tone
     error, not other words. The thresholds come from the user's 73 takes
     (`rescore.py --probe`) after the lessons were rebuilt with the ASR drift
     fix (FunASR's sentence_info had drifted from the clips; the first
     calibration had to leave lesson 2 out): own-sentence similarity
     p0/2/5/50/95/98/100 = 0/0/0.151/0.792/1/1/1, the next sentence's text
     0/0/0/0.134/0.5/0.5/1.0. Genuine takes with a few mispronounced words
     land at 0.43–0.5 (他们在睡觉 heard 他们在次微笑: 0.5), hence the middle
     band. Limits: a neighbouring sentence sharing most of its words can
     pass (next-sentence p95 0.5 is only noticed, max 1.0); genuine takes
     have a low tail (misreads, empty or stray transcripts) that is
     rejected. The
     letter-level fallback applies only when Latin letters are at least half
     of the transcript's characters. When the recogniser is busy (an ingest
     job holds it for a whole video) a take waits at most 2 s, then skips the
     check (`heard_text`/`text_sim` null, logged) and is tone-scored.
   - mean alignment confidence (step 3) is below `min_align_conf` →
     `wrong_or_unclear` (a garbled take lands here; the words check catches
     different sentences, whose confidence overlaps genuine takes: Task 15
     probe, wrong-text p5 0.043, p50 0.197).
   `min_align_conf` and `min_rms_dbfs` are set from the user's existing takes
   during implementation and recorded in the plan ledger.
3. **Align** the learner WAV to the segment text with `deps.aligner`
   (MMS_FA), the same aligner as the reference. Calls are serialised with a
   lock shared with ingest.
4. **Pitch** with parselmouth: autocorrelation, 10 ms step, floor 60 Hz,
   ceiling 500 Hz; if the voiced ratio is under 50 %, retry once with
   40–600 Hz. The reference clip's pitch is computed once per segment and
   cached (keyed by segment id and clip file mtime, so edits invalidate it).
5. **Normalise** (§2): `st = 12·log2(f0 / baseline_hz)`, divided by the
   speaker's spread when `normalise_span` is on.
6. **Per syllable**: slice by the alignment span, trim 15 % at each end,
   interpolate voiced frames to a 20-point contour; fewer than
   `min_voiced_frames` voiced frames → `unvoiced`. Features (§4.2) are
   computed by the same code for reference and learner.
7. **Classify and compare** (§3).
8. **Store** the score JSON on the attempt (§5.1) and one `SyllableScore` row
   per syllable.

## 2. Speaker baselines

A baseline is `(baseline_hz, spread_st)`: the median voiced F0 and the
interquartile range in semitones around it.

- **Reference speaker: whole lesson.** Computed over the voiced frames of all
  the lesson's segment clips, once, and stored in `Lesson.meta_json["pitch"]`
  (`{baseline_hz, spread_st, frames}`). Computed lazily on the first scored
  take of a lesson (≈ 1–5 s once). Not recomputed after edits: one edited
  sentence barely moves a lesson-wide median.
- **Learner: voice profile.** One `VoiceProfile` row per installation keeps a
  reservoir of recent voiced F0 values (the last 6000 voiced frames ≈ 60 s of
  speech, stored as JSON) and the derived `baseline_hz`, `spread_st`,
  `voiced_s`. Each scored take adds its voiced frames *after* it is scored.
  While `voiced_s` < 60, the take's own statistics are blended in with weight
  `1 − voiced_s / 60`, so the first takes work. Settings shows the profile and
  can reset it.
- **Training data** (§4) uses the same definition per AISHELL-3 speaker, over
  all of that speaker's utterances, so features mean the same thing in
  training and in the app.

## 3. What a syllable's score means

**Tones** are numbered 1–4 and **0 for neutral** throughout (as `words_json`
already does).

**Target tone** — the tone the speaker actually produced: the classifier's
top class on the *reference* syllable when its probability ≥
`ref_confidence` (0.6); otherwise the canonical tone from `words_json`
(pypinyin with sandhi). Sandhi (你好 → ní hǎo), 一/不 and half-third tones
therefore follow the speaker without hand-written rules. `SyllableScore`
keeps both `tone` (canonical) and `target_tone`.

**Score (0–1, shown ×100):**

```
p_target = classifier P(target tone | learner syllable)
contour  = 1 − clamp(DTW(ref contour, learner contour) / dtw_norm, 0, 1)
tone_score = tone_weight · p_target + (1 − tone_weight) · contour
```

DTW over the two 20-point contours, Sakoe–Chiba band `dtw_band` (4).
`dtw_norm` comes from the model's metadata (§4.4), chosen so that a typical
native-vs-native pair of the same tone in the same context scores a contour
similarity of 0.9. For a **neutral** target the contour term has weight 0
(`tone_score = p_target`).

**Status and colour** (`heard_tone` = the classifier's top class on the
learner syllable):

| status | rule | cell |
|---|---|---|
| `ok` | `heard_tone == target` and `tone_score ≥ green_at` (0.7) | green |
| `close` | not `ok` and not `wrong` | orange |
| `wrong` | `heard_tone ≠ target` and `P(heard) − p_target ≥ wrong_margin` (0.25) | red, shows `3→2` |
| `unvoiced` | too few voiced frames (either track) | grey `∅`, no score |
| `missing` | gate failed, or the learner span is shorter than 30 ms | dashed outline `–`, score 0 |

`suspect` stays reserved for Phase 3 segmental feedback. This replaces the
main spec's colour for `missing` (was red).

**Sentence:** `tone_overall` = mean `tone_score` over syllables that are not
`unvoiced`, with `missing` counted as 0; null when every syllable is
unvoiced or the gate failed. In Phase 2 `overall = tone_overall`.

## 4. The tone model (offline, once)

### 4.1 Data

AISHELL-3 (OpenSLR SLR93, Apache-2.0; 218 native speakers, ~85 h, character
and pinyin-with-tone transcripts). Downloaded by the tool into
`data/corpora/aishell3/` (gitignored). The first plan task checks whether the
transcripts' tones are canonical or realised (sandhi applied); if canonical,
the tool applies the same sandhi rules as `enrich` (3-3, 一, 不) to the labels
so the model learns realised tones. Erhua and characters without a tone label
are dropped. About 30 h (a fixed random subset of utterances, all speakers)
is used.

### 4.2 Features (`shadow/scoring/features.py`, `FEATURE_VERSION = 1`)

Shared by the training tool and the app. Per syllable, on normalised
semitones:

- the 20-point contour, its mean, slope of each half, min, max, and
  position of the minimum;
- voiced ratio and duration relative to the sentence's mean syllable
  duration;
- relative position in the sentence (declination);
- previous and next syllable: 5-point contours, mean and voiced ratio
  (zeros and a flag at sentence edges).

### 4.3 Training (`make tone-model`)

`backend/scripts/tone_model.py` runs: download (resumable) → read labels →
align each utterance with `MmsAligner` (the app's aligner, so training sees
the same boundary errors) → parselmouth pitch → per-speaker baselines →
features → `HistGradientBoostingClassifier` (scikit-learn, 5 classes).
Speakers are split 85 / 15 into train and held-out test; nothing of a test
speaker is seen in training. Intermediate features are cached as `.npz` so
retraining skips alignment.

### 4.4 Output

`backend/shadow/scoring/models/tone_v1.joblib` (a few MB) and
`tone_v1.json`: feature version, class order, `dtw_norm`, held-out accuracy
per tone, confusion matrix, corpus subset, date. Both are committed. The app
loads the model lazily; a feature-version mismatch is treated as "no model".

`dtw_norm`: over held-out pairs of syllables with the same realised tone and
the same neighbouring tones from two different speakers, `dtw_norm = median
DTW distance / 0.1`, so the median native pair scores a contour similarity of
exactly 0.9.

**Acceptance:** held-out accuracy ≥ 85 % over all classes. Below that the
plan stops for a decision (more data, richer features, or a small neural
model) before the app relies on it.

## 5. Data and API changes

### 5.1 Score JSON (per attempt)

Main spec §5 shape, with these changes: `segmental_overall`/`seg_score` stay
null; each syllable gains `target_tone`, `heard_tone`, `p_target`,
`contour`, and `status` uses §3's values. `ref_contour` / `usr_contour`
become `{t0_s, step_ms, f0_st, spans}`: `f0_st` in normalised semitones with
`null` for unvoiced frames, `t0_s` the time of the first frame and `spans` the
`[start_s, end_s]` of each syllable, both on the clip's / stored take's own
time axis (the trim offset already added back). Plus `model_version` and
`feature_version`. A take that failed the gate or could not be scored has
`overall: null`; every reader of `overall` must allow null. `warnings` uses the
gate codes of §1 plus `no_tone_model`, `align_failed` (span count does not
fit), `no_voice`, `no_reference` (no clip or alignment) and `score_failed`
(any exception). Each score also carries `quality: {dbfs, clipped,
align_conf, text_sim}` for setting the gate thresholds, and `heard_text`, what
the recogniser heard (punctuation kept); `heard_text` and `text_sim` are null
when the words check did not run. `notices` lists remarks on a scored take
(`words_differ`, §1) and is `[]` otherwise; older score JSON has no `notices`,
so readers treat it as absent = `[]`.

### 5.2 Tables

- `SyllableScore` gains `target_tone: int | None`, `heard_tone: int | None`.
- New `VoiceProfile(id, frames_json, baseline_hz, spread_st, voiced_s,
  updated_at)`.
- `init_db` gains a minimal "add missing columns" step (SQLite `ALTER TABLE
  ADD COLUMN` for nullable columns) so existing databases upgrade in place.

### 5.3 Endpoints

- `GET /lessons/{id}/takes` → each take also carries `score_json`.
- `GET /stats/tones` → also `weeks: [{week, tone, mean, n}]` (ISO week of the
  attempt, last 12 weeks) and pairs keyed by **target** tones; per-tone
  means use the target tone.
- `GET /stats/syllables` → per character: `ch`, pinyin, mean, n, and the
  last-10 vs. previous mean as trend.
- `GET /voice-profile`, `DELETE /voice-profile` (reset).
- `/health` adds `tone_model: {loaded, version, accuracy}`.

### 5.4 Rescore

`make rescore` (`backend/scripts/rescore.py`): rebuilds every attempt's
score JSON and `SyllableScore` rows, oldest first, rebuilding the voice
profile from scratch along the way. Run once for the existing takes and after
any model or feature-version change. Also writes a **sanity report**
(`data/reports/rescore-<date>.html`): per take, the sentence, the per-syllable
target / heard tone / score / status, and audio links for reference and take,
so the user can skim whether red lands where it sounds wrong.

## 6. UI

The feedback block keeps its shape (main spec §7.2).

- **Pitch lines:** on the You track, the learner's normalised contour over
  the waveform, with the reference contour drawn faintly behind it (on the
  learner's time axis, syllable by syllable via the alignment); on the
  Reference track, the reference contour. Unvoiced stretches are gaps.
- **Cells:** colour by status; the score; red cells show `3→2` (target →
  heard). Hover: "Speaker: tone 3 · You: tone 2 · 41".
- **Score chips:** overall (large), tone, best so far, attempts. Segmental
  chip reads "Phase 3".
- **Gate warnings** replace the score in the header and show in the hint
  line under the transport ("Too quiet — not scored. Move closer to the
  mic.").
- **Stored takes** carry their score, so a reopened lesson shows colours; the
  segment's `last_score`/`best_score` in the store update from the upload
  response.
- **Flow:** transcript rows take their score colour as each slice's score
  returns; the summary's mean and weakest lines work as already built.
- **Stats:** per-tone means as a small line chart over 12 weeks; a 5×5
  tone-pair matrix (previous target tone × target tone, cell = mean, n on
  hover; cells with n < 5 dimmed); weakest characters with trend arrows.
- **Settings → Voice profile:** "Your baseline: 118 Hz · range 9.5 st · from
  4.2 min of speech" and **Reset**.

## 7. Error handling

A take is always saved and replayable. If the model file is missing or
mismatched, pitch extraction fails, alignment raises, or the recogniser of
the words check (§1) raises (the most likely failure when offline with
Paraformer not yet cached → `score_failed`), the score JSON is
`{overall: null, warnings: [...]}` with no `SyllableScore` rows, and the UI
shows the warning where the score would be. `/health` shows whether the tone
model loaded. Scoring errors are logged with the attempt id.

## 8. Testing

- Unit: trim, gate (each code), normalisation, baselines and profile
  blending, features (fixed input → fixed vector), DTW/contour, target-tone
  choice, status rules, sentence aggregation, DB column migration.
- Synthetic errors (needs parselmouth, no corpus): a reference clip is
  resynthesised with one syllable's pitch replaced (a 4 flattened, a 2
  inverted) using parselmouth `Manipulation`; with a stub classifier the
  contour term must drop for that syllable only; with the real model
  (`-m models`) that syllable must not be `ok` and an untouched resynthesis
  must have no `wrong` syllables.
- API: upload → score JSON + rows; takes carry scores; stats shapes; voice
  profile get/reset; health.
- Frontend: cell colours and `3→2`, pitch-line rendering from contours,
  chips, gate warnings, stored-take scores, stats matrix and chart, settings
  profile.
- Model quality is measured by the training run (§4.4), not by `make test`.

## 9. Build order

1. Dependencies (parselmouth, scikit-learn, joblib), config keys, DB changes.
2. Pitch, trim, gate, baselines, features, DTW — pure functions with tests.
3. Training tool; run it; accept or stop at §4.4.
4. `score_attempt` wiring, voice profile, rescore + sanity report; set gate
   thresholds from the user's takes.
5. API changes (takes, stats, voice profile, health).
6. Frontend: cells, chips, pitch lines, stored scores, Flow colours.
7. Stats and Settings.
8. Docs: README roadmap, `docs/running.md` (training and rescore),
   acceptance checklist `docs/phase2-acceptance.md`.

## 10. Revision 2026-10-11: speech-model tone features

The pitch-only classifier of §4 reached 75.1 % on held-out AISHELL-3 speakers
(30 h; neutral 51 %, third tone 68 %) and would have marked about one correct
syllable in six red. the user chose to classify tone from a pretrained Chinese
speech model instead. A spike on 40 training / 10 held-out speakers measured,
per hidden layer of `TencentGameMate/chinese-wav2vec2-base` (MIT, 95 M
parameters, 360 MB), mean-pooled over each aligned syllable with logistic
regression: layer 0 65.5 %, 3 85.5 %, 6 **93.6 %** (best), 9 91.1 %,
12 80.5 %; pitch-only on the same data 71.6 %. Layer 6 with the previous and
next syllables' embeddings and the 45 pitch features, through a small MLP:
**95.9 %** (per tone 0: 91, 1: 97, 2: 95, 3: 96, 4: 97 %). Model forward:
13 ms per 3 s take on the GPU (435 MB peak, fp32), 345 ms on the CPU.

This section replaces §4.2–§4.4 where they differ, and one rule of §3.

- **Embedder.** `chinese-wav2vec2-base` at a pinned revision
  (`3991242c806928916fff4a8c0e4f76acf661b743`), fp32, raw 16 kHz waveform
  input (no extra normalisation, as in the spike), hidden state 6
  (`hidden_states[6]`, i.e. after the sixth transformer layer). Loaded lazily
  on first use, on the configured device; calls serialised with a lock.
  Config `[models] tone_embedder`, `tone_embedder_revision`, `tone_layer`.
- **Pooling.** Per syllable span, the mean of the frames whose centre
  (`i·20 ms + 12.5 ms`) lies inside `[start, end]`; the nearest frame when
  none does.
- **Features (`FEATURE_VERSION = 2`).** `[own embedding (768), previous
  syllable's embedding (768), previous present (1), next syllable's embedding
  (768), next present (1), the 45 pitch features of §4.2]` = 2351 values.
  Missing neighbours are zeros with the flag 0.
- **Model.** `StandardScaler` + `MLPClassifier(hidden_layer_sizes=(256,),
  early_stopping=True, random_state=0)` in one scikit-learn pipeline, trained
  on **every labelled syllable**, voiced or not, from 15 h of AISHELL-3
  (`--hours 15`, realised labels). `dtw_norm` is computed as before from the
  pitch contours of voiced syllables. Acceptance stays ≥ 85 % on held-out
  speakers.
- **Unvoiced syllables (replaces the §3 rule).** A syllable whose pitch is
  unvoiced on either track is still classified: it gets no contour term
  (`tone_score = p_target`, like a neutral target) and normal ok / close /
  wrong status. `unvoiced` (grey ∅) remains only for non-hanzi characters
  (tone −1). The pitch lines still show a gap there.
- **Reference.** The reference clip's embeddings are computed per scoring
  call (13 ms); not cached.
- **Memory.** About 0.45 GB of GPU memory in addition to the aligner. On a
  CPU-only machine scoring a take takes about 0.4 s longer.
- `/health` lists `embedder` among loaded models once it has been used.

### 10.1 Revision 2026-10-11 (second spike): wrong-tone robustness and syllable windows

The speech-model classifier trained on native speech alone leaned on character
identity: on held-out speech whose pitch was replaced (PSOLA) with another
tone's contour it scored 47 %, and with flat pitch it still named the
original tone 2/3/4 for 59 % of syllables. A learner's wrong tone on the right
syllable would often have been passed. Trained with pitch-altered copies it
holds up (10 held-out speakers):

| classifier | native | false "wrong" on native | altered | flat: still says original |
|---|---|---|---|---|
| embedding MLP, native only | 95.7 % | 3.9 % | 47.0 % | 59.4 % |
| **embedding MLP, native + altered** | **94.0 %** | **5.7 %** | **95.1 %** | **14.5 %** |
| pitch-only, native only | 76.2 % | 16.7 % | 73.7 % | 10.9 % |

The same spike found that MMS spans cover only about the first half of each
syllable (CTC peaks); widening them lifted pitch-only accuracy 71.5 → 76.5 %.

Binding changes:

- **Syllable windows.** Pitch slicing, embedding pooling and the contour
  spans in the score JSON use each syllable's *window*, not its raw aligner
  span: from the span's start to the next span's start, unless that lies
  more than 0.5 s after the span's start (then: span end + 0.15 s, never
  past the next start); the last syllable runs to span end + 0.15 s, never
  past the audio's end; a window never ends before its span's end. The
  `missing` check (span shorter than 30 ms) still uses the raw span.
- **Training data.** Per training utterance: the native recording plus two
  pitch-altered copies. In an altered copy every syllable's window gets a
  contour drawn from {1, 2, 3, 4, flat} other than its own tone, imposed with
  parselmouth (Manipulation, PitchTier, overlap-add resynthesis) as five
  points at 5/27/50/73/95 % of the window. Contours are Chao-style levels
  relative to the speaker's baseline: one level = 0.6 × the speaker's spread
  (semitones), centred on level 3, templates 1: 55555, 2: 3·2.7·3·4·5,
  3: 2·1.3·1·1·(random 1–3), 4: 5·4.5·3.5·2·1, each scaled by a random
  0.7–1.3 and shifted by a random ±0.3 spread units; flat = the speaker's
  median, labelled tone 1. An altered syllable is labelled with the imposed
  tone; altered syllables whose own tone is neutral or unlabelled are not
  used. The original alignment is reused for the altered copies.
- **Acceptance.** On held-out speakers: native accuracy ≥ 85 % **and**
  accuracy on one altered copy per held-out utterance ≥ 85 %; the training
  run also reports the false-"wrong" rate on native speech and, on an
  all-flat copy, the share still classified as the original tone 2/3/4.
- **Size.** 10 h of native recordings (≈ 3× that in rows with the altered
  copies) to stay within 8 GB RAM.
