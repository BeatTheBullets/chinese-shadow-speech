Short version: there's no open-source "Trancy for Chinese" with scoring, but the pieces exist and a couple of repos are close enough to fork.

Closest shadowing-loop repos

Hibiki (JulianPJ/Shadowing) — Japanese, but the most complete architecture. Sentence/clause segmentation from punctuation, caption timing and pauses; a shadowing mode that pauses at section boundaries so you can repeat, record, and listen back, with a separate faster-whisper service on CPU. Pronunciation scoring is deliberately not implemented, but there's a PronunciationAnalysisProvider extension interface — i.e. a hook sitting right where you'd plug tone scoring in. Retargeting to Mandarin is mostly swapping the Whisper language and the segmentation rules. 
GitHub - JulianPJ/Shadowing · GitHub +2
écho (EricWay1024/echo) — local-first workbench for shadowing from YouTube audio, where an LLM cleans and segments the transcript without losing word-level timing. The pipeline is mostly language-agnostic but prompts and pronunciation data assume French. Worth stealing the transcript-rectification trick: Whisper's raw Chinese segments are often badly punctuated, and that's what ruins sentence-by-sentence shadowing. 
github
github
Dthurow/SpeechShadowing — minimal Python GUI: upload native audio, split into sentences by silence, record yourself, play both back-to-back. Basically a weekend version of the article's workflow, no scoring. 
github
674019130/shadow-reading — English, Next.js; nice UX reference with wavesurfer player with speed control, synced SRT/VTT subtitles, a 5-phase guided 20-minute session, sentence loop, and side-by-side record/compare. 
github
There's also a thomashirtz/chinese-shadowing repo on the GitHub shadowing topic page, but I couldn't open it to see how far along it is.

Scoring building blocks

Halleck45/OpenPronounce — phoneme-level pronunciation assessment using Wav2Vec2 + DTW, pitched as a self-hosted alternative to Azure Pronunciation Assessment. English-first, but it phonemizes the expected sentence with espeak-ng in the selected language, so it's the right shape for the Trancy-style per-word green/orange/gray — just not tones. 
github
github
efancher/shadowing-analysis-api — Japanese, but captures the key design insight: when the exact sentence plus a native reference and a learner recording are all known in advance, forced alignment, not open-vocabulary ASR, is the right tool. That's exactly your situation. 
github

Tone scoring specifically

Nothing polished and open. What exists:

Research: a 2025 paper that evaluates L2 Mandarin tone pronunciation with a ResNet-based Siamese network, using standard-accented Mandarin as the reference and training on THCHS-30 and AIShell — Siamese = "compare learner to reference", which maps perfectly onto shadowing. Also OMPAL, an open corpus of 1,768 Mandarin utterances from French L1 learners with expert word- and sentence-level scores, plus a public baseline model, and a recent arXiv paper on phonological-level Wav2Vec2 for Mandarin mispronunciation detection. 
nature
academia
Hobby repos: claw89's CNN+RNN tone classifier on spectrograms and cglangs/toneapp, a fastai model trained on the Tone Perfect dataset that excludes the neutral tone. Both are isolated-syllable classifiers — they fall apart on connected speech with sandhi and neutral tones. 
github
github

The good news is that shadowing makes tone scoring easier than generic assessment, because you always have the native reference for the same sentence. You don't need a model trained on learner data; you need alignment plus contour comparison:

Convert the sentence to syllables with pypinyin; force-align both the reference and your recording to those syllables (Montreal Forced Aligner has Mandarin models; a wav2vec2-CTC aligner via torchaudio is the lighter path).
Extract F0 per syllable (parselmouth/pyworld/CREPE), normalise to semitones relative to each speaker's median so your voice vs. a female YouTuber's doesn't matter.
Score each syllable by DTW distance between your contour and the reference contour. Comparing to the actual reference rather than canonical tone templates handles third-tone sandhi, neutral tones and coarticulation for free.
Render it as two overlaid pitch lines per syllable — honestly more useful than a number, and it's the thing Trancy doesn't give you.