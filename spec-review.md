# Review of `shadowing-tool-spec.md` — feasibility and design notes

Date: 2026-10-03. Sources: the spec, the naturallanguagejourney.com article it is
based on, the earlier claude.ai survey (`Context_claude_ai.md`), two research
passes (shadowing literature; current status of every library and model the
spec names), and a check of the local machine.

## 1. Verdict

The tool is feasible and the overall architecture is sound. Three things in the
spec are wrong or fragile enough that they should change before building:

1. **Whisper word timestamps for Chinese do not work.** Whisper only starts a
   new "word" at a leading-space token; Chinese has none, so a segment often
   comes back as one word. The sentence splitting (§2.3) assumes a flat list
   of timed 1–3 character tokens that Whisper will not deliver. Fix in §3.1.
2. **The v1 segmental scorer will be noisier than the learner.** The Chinese
   wav2vec2 CTC models the spec points at have a 12–19 % character error rate
   on *native* read speech. A diff against their output flags roughly one in
   six characters wrongly before the learner has made a single mistake. Fix
   in §3.3.
3. **YouTube download from a server is now unreliable.** yt-dlp needs a JS
   runtime (Deno), PO tokens via a plugin, and often browser cookies; WSL and
   datacenter IPs get "confirm you're not a bot". Uploads should be the primary
   path and YouTube the optional one, not the reverse.

Everything else holds up, with the smaller corrections listed in §4. The local
machine (WSL2, 12 cores, RTX 3070 8 GB, but only 7.7 GB RAM visible to WSL)
makes the GPU path easy and the CPU-only targets in the spec borderline.

## 2. What shadowing is, and what that implies for the design

### 2.1 Two traditions

- **Interpreter / Japanese EFL tradition** (Tamai, Kadota, Hamada): shadowing
  is *near-simultaneous* repetition, lag close to zero, so perception is
  trained online. "If shadowing is mistaken for listen-and-repeat, the purpose
  will be lost." Progression: listen → mumble → parallel reading with script →
  prosody shadowing without script → content shadowing. Material at i-1 (two
  or three unknown words per hundred). About five passes over one text, then
  stop; gains plateau after that.
- **Argüelles / autodidact tradition**: walk fast, speak loudly on top of the
  recording, blind first, then with bilingual text in several stages, then
  blind again. About 15 minutes per block, several blocks a day.
- **Chorusing** (Kjellin; promoted by Refold as "the single most effective
  pronunciation exercise, especially for prosody, rhythm and tone"): loop a
  clip under five seconds and speak *with* it ten to fifty times until timing
  and melody match.

The article the spec is built on is a hybrid: silent listen → whisper along →
record without text, review, re-record once if needed, move on after several
tries, no more than 20 minutes, one consistent speaker, hide text while
recording so you listen instead of read. Trancy's colours (grey omitted,
orange mispronounced, green correct) come from that article.

### 2.2 What the evidence says

- Shadowing reliably improves **comprehensibility, fluency and prosody**
  (Foote & McDonough 2017; Mori 2011; Whitworth & Rose 2025 systematic review
  of 44 studies). Effects on **segmental accuracy and accentedness are
  inconclusive**; Foote & McDonough found no change in accentedness.
- For **Mandarin tones**, Lu & Su 2024 found four weeks of sentence-level
  shadowing improved tone accuracy in spontaneous speech (small n, no
  no-shadowing control).
- Shadowing alone did not fix phonemic discrimination; adding **corrective
  feedback** did (Hamada 2020). Feedback is justified, not decoration.
- **Visual pitch-contour feedback works**: learners comparing their Praat F0
  curves with native ones improved tones (Chun et al. 2015, 9 weeks, 20–25
  min/week); Chen 2022 found Praat contours plus corrected audio beat teacher
  feedback. Olson & Offerman 2020: visual feedback works best one feature at a
  time, over sustained practice.
- Connected-speech tones deviate from citation shapes, sometimes beyond
  recognition (Xu 1997; Lu, Chuang & Baayen 2025 show T2-T3 and T3-T3 fully
  neutralise in spontaneous Taiwan Mandarin). Half-third tone (low, no rise) is
  the normal realisation before another syllable. **Scoring against the native
  recording rather than dictionary tones is the right call**, and the spec
  already makes it.

### 2.3 Design implications

| Evidence | Spec today | Recommendation |
|---|---|---|
| Gains are in prosody and tone, not segments | Segmental scoring is Phase 2, tone Phase 3 | Swap: tone and overlay first (also lower technical risk, see §3.3) |
| Near-simultaneous shadowing and chorusing are the core drills in both traditions | Loop is listen → record (delayed) | Add a **speak-along / chorus mode** in Phase 1: play the clip N times on loop while recording; headphones required. Cheap to build. |
| Hide text while recording | Hanzi + pinyin visible by default | Keep text visible during playback, auto-hide during recording, configurable |
| Five passes then plateau; move on when stuck | "Move on" hint after 4 attempts | Keep. Also show per-lesson pass count, nudge after 5 |
| ~20 min then fatigue | Timer turns amber at 20 min | Keep |
| One consistent speaker | Library grouped by channel | Keep |
| Whole-utterance contour matters (coarticulation, declination) | One small panel per syllable | Make a single sentence-wide overlay with syllable boundaries the primary view; per-syllable panels secondary |
| 75 % speed is the common advice; Kadota prefers easier material | 0.6–1.0 slider | Keep, default 0.75 as the one slow option (see §4 on implementation) |

## 3. Component-by-component feasibility

| Component | Spec choice | Status (2026-10) | Verdict |
|---|---|---|---|
| ASR text | faster-whisper large-v3-turbo | Works (`turbo` or deepdml CT2). CER ~22 % on Chinese vs 8–10 % for FunASR SenseVoice/Paraformer; Traditional/Simplified drift; hallucination on silence | Partly. Prefer Paraformer-zh or Belle-whisper-zh-punct |
| ASR timing | Whisper word timestamps | Structurally broken for zh (one "word" per segment) | **Wrong**. Use a forced aligner |
| Forced alignment | torchaudio `MMS_FA` | Survives torchaudio's maintenance mode (pin ≥ 2.10; load audio with soundfile, not torchaudio.load). Romanised toneless input. CPU ~0.5–2 s per sentence. Boundary error of CTC aligners ~130 ms | Confirmed, but boundary precision is the hidden crux for tone slicing |
| Alignment alternative | MFA (conda) | Mandarin v3 models exist; conda-only; batch-oriented | Partly. Better: **Qwen3-ForcedAligner-0.6B** (Jan 2026, Apache-2.0, raw hanzi in, char times out, 43 ms mean error, GPU) |
| Segmental ASR | Chinese wav2vec2 CTC, no LM | `wbbbbb/wav2vec2-large-chinese-zh-cn` CER 12.3 %, `jonatasgrosman/...` 19 %, `kehanlu/mandarin-wav2vec2-aishell1` 5.1 % but non-commercial licence | Confirmed as models; **risky as a 3-way label source** |
| GOP (v2) | CTC posteriors | Active literature (Interspeech 2024/25, Mandarin tone-attribute MDD repo 2026); no turnkey package | Partly; self-implement |
| F0 | parselmouth | 0.4.7, wheels for py3.12. Best accuracy/speed trade-off among trackers; pYIN is the weakest option | Confirmed |
| Pinyin | pypinyin | `tone_sandhi=True` covers T3+T3, 不, 一 only; ~87 % polyphone accuracy without jieba/g2pW | Partly; add jieba pre-segmentation |
| TTS fixtures | edge-tts | Works today, breaks every few months, blocked from cloud IPs | Risky. Use Kokoro-82M-v1.1-zh offline once, commit WAVs |
| YouTube | yt-dlp | Needs Deno + PO-token plugin + cookies | Risky; make optional |
| Browser recording | `audio/webm;codecs=opus` | iOS < 18.4 records `audio/mp4` only | Partly; probe and fall back |
| Slow playback | AudioBuffer + rate | `AudioBufferSourceNode.playbackRate` shifts pitch; only `HTMLMediaElement.preservesPitch` keeps it | Gap in spec |
| Ingest target: 10 min in < 5 min on CPU | Whisper turbo int8 | Estimated 5–8 min on a 6-core Ryzen | Missed on CPU; trivial on the 3070, or < 1 min with Paraformer |
| Score target < 1.5 s | | F0 ms, alignment 0.5–2 s CPU, CTC ASR ~0.5 s | Borderline CPU, easy GPU |

### 3.1 Fix for ingestion: separate text from timing

Stop treating ASR output as timed tokens. Make text and timing independent:

1. **Text**: best available source, in order: uploader `zh` subtitles → Chinese
   ASR (Paraformer-zh via FunASR gives punctuation and simplified output
   natively; or Belle-whisper-zh-punct CT2 int8 as a faster-whisper drop-in).
   Keep segment-level times only (±1 s is enough).
2. **Segment** over *character* indices of the raw text at punctuation and
   segment ends, as ranges, so timing stays attached.
3. **Force-align** each corrected sentence to the audio inside its segment
   window (padded 1 s). This yields character/syllable times for the reference
   and is the same alignment call the scorer needs, so cache it. Manual
   character edits now cost nothing because timing is recomputed from the
   corrected text.

If human subtitles exist, skip ASR entirely: cues already carry timing and
are split at punctuation; alignment supplies syllable times.
This removes the subtitle-to-Whisper edit-distance matching in §2.2 of the spec.

### 3.2 Alignment is the hidden crux

Tone scoring trims 15 % off each syllable edge and interpolates to 20 points. A
130 ms boundary error on a 200 ms syllable destroys the contour. Before any
scoring work, run a 30-minute bake-off on TTS fixtures with known boundaries:
MMS_FA, `ctc-forced-aligner`, Qwen3-ForcedAligner (GPU), and the Chinese
wav2vec2 model through `torchaudio.functional.forced_align`. Pick by boundary
error, keep the aligner interface the spec already defines. With a 3070 in the
machine, Qwen3-ForcedAligner is the likely winner and also removes the
pinyin-romanisation step.

### 3.3 Segmental scoring: go straight to GOP, or demote it

ASR-diff against a model with 12–19 % CER on native speech cannot give a
trustworthy 3-way label. Two better options:

- **GOP from the same CTC model used for alignment** (one model, one pass):
  log-posterior of the expected character versus the best competitor within
  the aligned span. Continuous score, threshold tuned on your own recordings.
  This is the spec's v2; it is not harder than v1 once alignment exists.
- **Demote segmental to "suspect" markers**: show orange only when GOP is far
  below the reference's own GOP for that syllable (reference clip scored
  through the same pipeline gives a per-syllable baseline).

Either way, build tone and the overlay first. It is what the evidence rewards,
it is what Trancy lacks, and it depends only on parselmouth and alignment.

## 4. Smaller corrections to the spec

- **Slow playback**: use an `<audio>` element with `preservesPitch` (widely
  supported since late 2023) for the reference instead of decoded
  `AudioBuffer`s, or pre-render a 0.75× clip with ffmpeg `atempo` at ingest.
  Latency difference for a preloaded 3-second blob is negligible.
- **Recording MIME**: probe `MediaRecorder.isTypeSupported`, fall back to
  `audio/mp4`, always transcode server-side; store the original.
- **Fixtures**: generate with Kokoro-zh and commit WAVs. For the pitch-flattened
  learner fixture use parselmouth's Manipulation/PitchTier (set to constant),
  not librosa pitch shift, which cannot flatten.
- **pypinyin**: `tone_sandhi=True`, `neutral_tone_with_five=True`, jieba
  pre-segmentation. Still display-only; polyphones need the `PATCH` fix path.
- **Data model**: add `session_id` to `Attempt`; store the reference alignment
  JSON on `Segment`; `PATCH /segments/{id}` with new text must invalidate
  pinyin, clip and alignment. `resplit at_char_index` becomes trivial: look up
  the character's time in the cached alignment.
- **Tone scorer**: mark creaky/low T3 frames as unvoiced rather than penalising
  (Praat often loses F0 there); add slope-sign agreement as the spec says, and
  consider z-normalising pitch span as well as median, since speakers differ in
  range, not only in height.
- **torchaudio**: pin ≥ 2.10; audio I/O via soundfile; do not rely on
  `torchaudio.load`.
- **Memory**: WSL shows 7.7 GB. Whisper turbo int8 (~1.5 GB) + wav2vec2 large
  (~1.2 GB) + aligner coexist only if loaded lazily or on GPU. Raise
  `.wslconfig` memory or run models on the 3070 (ctranslate2 needs cuDNN 9
  wheels in WSL).
- **Hosting**: no auth, so bind to localhost or a Tailscale interface on the lab
  server; say so in the spec.
- **Scope note**: the spec is roughly four independent subsystems (ingest,
  practice loop, alignment+tone, segmental). Phases already reflect this; keep
  each phase a separate spec-and-plan cycle.

## 5. Recommended phase order

0. Skeleton as specified.
1. **Loop without scoring**, with upload as the primary ingest path, Chinese
   ASR (Paraformer or Belle-whisper), segmentation over characters,
   forced alignment for clip boundaries, speak-along/chorus mode, auto-hide
   text while recording. Daily-usable milestone.
2. **Alignment bake-off, then tone overlay and tone score.** Sentence-wide
   contour overlay as primary view; per-tone stats.
3. **Segmental via GOP** from the alignment model; orange only on confident
   deviation.
4. Polish: guided mode, review queue, library by channel, YouTube path with
   cookies, MFA option if boundary precision still matters.

## 6. Decisions for you

1. Accept swapping tone before segmental, and GOP instead of ASR-diff?
2. ASR: FunASR Paraformer-zh (heavier install, better Chinese, CPU-fast) or
   stay in the Whisper family with Belle-whisper-zh-punct (drop-in)?
3. Design target: CPU-first as the spec says, or assume the RTX 3070 and treat
   CPU as degraded? This decides whether Qwen3-ForcedAligner is the default.
4. Speak-along/chorus mode in Phase 1 or later?
5. Uploads as the primary ingest path, YouTube optional with cookies?
