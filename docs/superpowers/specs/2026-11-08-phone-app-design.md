# Chinese Shadow Speech on phones: design

Date: 2026-11-08. Status: approved by the user on 2026-11-08.

## 1. Intent

The PC app (Python backend + React UI, v0.2.0) is the full shadowing tool: build lessons from YouTube or your own
audio, practise sentence by sentence (Echo) or continuously (Flow), and get every syllable's tone and sounds scored
against the speaker, offline, by on-device models. This project puts the same tool on iPhone and Android, free in the
App Store and Google Play, for anyone who finds it there.

The moment it is for: a learner on the bus or train, offline, opens the app and practises a lesson they downloaded
earlier. **Practising is the same as on the PC**: same modes, same scoring, same verdicts.

Why it is worth doing: a feasibility spike (2026-11-08, §9) showed the full set of models runs on a phone fast
enough and with the same verdicts, so phones are not a reduced version of the app.

## 2. Goals, non-goals, anti-goals

**Goals (first store release has all of them)**
- Practise: Echo and Flow, scored exactly as on the PC (tone, sounds, words check, pitch curves).
- Lessons made on the phone itself, from three sources:
  1. **Podcasts** (RSS feeds): the store-safe online source.
  2. **Your own audio files** (from Files / share sheet).
  3. **Lessons made by the PC app**, exported as one file and opened on the phone. This is how YouTube lessons reach
     the phone; the phone app itself never touches YouTube.
- Library, Review, Stats, Drills, Anki, Settings: everything the PC app has.
- Everything works offline once the models and the lesson are downloaded.
- Runs on iPhone (test device: iPhone 17) and Android (test device: Motorola Edge 30 Neo, a midrange phone), including
  phones with 4 GB of memory through a low-memory mode (§4.6).
- A phone-shaped UI, with long sentences shown clause by clause (§6).
- Testable on the user's own iPhone and shareable with friends before the stores (TestFlight; Play testing tracks).

**Non-goals**
- YouTube or Bilibili inside the phone app, in any form, including the embedded player (§4.3 says why).
- Accounts, sync between devices, a server of our own. Moving a lesson from PC to phone is a file.
- Rewriting the PC app. It stays Python; it only gains "Export lesson" (§4.3).
- Tablets, landscape layouts, watches.
- Phones with less than 4 GB of memory. They are filtered out on Google Play; on iPhone they get a clear message.

**Anti-goals (it would be a failure even if it "works")**
- Scores that differ from the PC's. Same take, same lesson: the phone and the PC must agree (§8).
- Practising that needs the internet.
- A store build that gets pulled for YouTube downloading, or that breaks a model licence.
- Ads, tracking, analytics. The app is free and open source like the PC app; the store privacy labels say
  "no data collected".
- Long sentences that are ugly or unreadable: overflowing, many broken lines, or characters too small to read.

## 3. Constraints

- **No Mac.** iOS builds and TestFlight uploads run on GitHub's macOS runners. Needs an Apple Developer account
  ($99/year, the user's), bought only when M0 reaches the iPhone. Android builds and the emulator run on the PC; the
  Motorola gets development builds over USB from the PC, which needs no store account.
- **The user's legal name must not be public.** An individual Apple account lists the legal name as the App Store
  seller, so the personal account is used for development and TestFlight only. Apple converts an individual membership
to an organisation one on request, keeping the membership and the apps, so starting personal costs nothing extra. Before the public release (M4) the
  user decides how to publish without it: an organisation account needs a legal entity (in the Netherlands a BV or a
  stichting; a one-person business counts as an individual) and a D-U-N-S number, which takes weeks. On Google Play
  the developer name is chosen freely; declare "non-trader" (free, no income) and use a dedicated contact email.
- **Licence for the App Store: open, decided before M4.** Apple's terms are widely held to clash with the AGPL. The
  user (sole copyright holder so far) decides before release whether to add an App Store exception; nothing before
  M4 depends on it.
- **Store rules.** Google Play: a new personal developer account must run a closed test with 12 testers for 14 days
  before the first public release. Apple: models may be downloaded after install as data (they are not code).
- **Licences.** The app is AGPL-3.0-or-later. The aligner (MMS_FA) weights are CC-BY-NC 4.0, so the app stays
  non-commercial (free, no ads, no in-app purchases). Every model we redistribute in converted form needs its
  licence checked and credited (THIRD_PARTY.md) before we host it.
- **Model size.** About 1.2–1.3 GB in total (int8 except the tone model, which stays fp32, §9). Downloaded on first
  launch, not inside the store package.
- **Memory.** About 2 GB peak natively with all four models loaded (measured on the PC). Has to be proven on the
  iPhone in milestone M0 (§10).
- **Repo rules.** Same repo, same rules: noreply identity, no names/emails/home paths, push from a fresh clone.

## 4. How it works

### 4.1 Shape of the app (decided by me; the user handed these choices over)

- **Shell: Capacitor.** The existing React UI runs in the app's web view, so the phone gets the same screens and the
  same code, reshaped for a phone (§6). A rewrite in React Native, Swift or Kotlin was rejected: it would mean two or
  three UIs to keep in step.
- **Models: native ONNX Runtime**, in a small native plugin (Swift on iOS, Kotlin on Android). Not the browser's
  ONNX Runtime: the spike showed Safari runs it on one core and kills the page at about 620 MB.
- **The backend's logic is ported to TypeScript** and runs in the web view, in place of the Python server: lesson
  building (segmenting, alignment, enrichment, passages), scoring (pitch, tone, sounds, words check, gates),
  stats, drills, review. The UI's API client calls this code instead of HTTP, with the same request and response
  shapes, so the screens barely change.
- **Storage: SQLite** on the phone (a Capacitor SQLite plugin), same tables as the PC (`store/models.py`). Audio files
  in the app's own storage.
- **Native plugin duties**, kept small: run a model on an array or on a file range; decode podcast/audio files
  (MP3, AAC, M4A, WAV…) to 16 kHz mono WAV on disk; record and play with the right audio-session settings (§4.4);
  keep a lesson build running when the screen locks, as far as each OS allows.

### 4.2 Models

The PC's models, converted to ONNX in the spike (`export_w2v.py`, FunASR's own export):

| Model | Job | Format | Size |
|---|---|---|---|
| Paraformer + fsmn VAD + punctuation | recogniser: what was said, with times | int8 | ≈ 260 MB |
| MMS_FA (wav2vec2-large) | aligner | int8 | 355 MB |
| wbbbbb wav2vec2-large-chinese | sounds model | int8 | 360 MB |
| chinese-wav2vec2-base, first 6 layers | tone embedder | **fp32** (int8 changed 7.5 % of tone verdicts) | 207 MB |
| tone classifier (MLP) | tone from embedding + pitch | weights as JSON or ONNX | small |

- Downloaded on first launch from files we host (GitHub Releases of this repo, unless a licence forbids it), with a
  progress bar, resumable, WiFi recommended, checksums checked. The app is usable for nothing else until they are
  in; it says so plainly.
- Only the models a job needs are loaded: lesson building holds recogniser + aligner; practising holds all four.
  Models are released when the app goes to the background for a while.
- Pitch: Praat's autocorrelation pitch, ported. A numpy port already matches parselmouth on every test file (100 %
  same voicing, ≤ 1e-6 semitones). It takes about 330 ms per second of audio in Python, which would add about 1.3 s to
  a 4 s take, so it goes in TypeScript only if it stays well under that; otherwise it goes in the native plugin
  (builder measures in M0). Praat and parselmouth are GPL, so the port is written from the published algorithm
  (Boersma 1993) and checked against parselmouth's output, not translated from Praat's source (§3, licences).
- Text: jieba segmentation, pypinyin with tone sandhi, OpenCC simplification have to be matched in TypeScript.
  Where no exact equivalent exists, ship the same dictionaries the Python libraries use.

### 4.3 Lesson sources

**Podcasts.**
- Find a show by searching (Apple's free podcast search API, which covers Android users too) or by pasting a feed URL.
- The show page lists episodes (title, date, length). The learner picks one; the app downloads the audio file from the
  feed's enclosure URL and builds the lesson on the phone, like an own file.
- Long episodes: the learner can pick a part to build (for example the first 10 minutes) so they can start sooner.
  Building runs while they do other things in the app and survives the screen locking where the OS allows; if it is
  interrupted, it resumes.
- Most Chinese podcasts have no transcript, so the recogniser makes one. Where a feed carries a transcript
  (`podcast:transcript`), use it the way the PC uses YouTube subtitles.
- Subscribing, new-episode alerts and auto-download are not in the first release (my call; see §11).

**Own audio files.** Open a file from Files / the share sheet / another app; build as on the PC.

**Lessons from the PC app.** New on the PC: "Export lesson" writes one file (a zip with a manifest, the segments
with text, pinyin, translations, timings and reference alignment, and the source audio). On the phone, opening that
file imports the lesson ready to practise, with no rebuilding. This covers YouTube lessons, Anki-built lessons and
anything else the PC can make. The format is versioned; the phone refuses a newer version with a clear message.

Why not YouTube's embedded player as an online-only source: the app never gets the audio, and scoring compares the
learner with the speaker's audio for every syllable (pitch and tone `score.py:121-125`, sounds `score.py:157`). It
would also need the internet. (Baolingo, an iOS app that does play YouTube this way, was researched on 2026-11-08.)

### 4.4 Practising

Same as the PC: Echo (listen, record, auto-play speaker then you, score) and Flow (continuous, `after` and `along`
sub-modes, slicing the recording by the playback schedule, then the Flow summary). Same scoring settings and
thresholds.

Phone specifics:
- Audio session set for playing and recording together (iOS play-and-record; Android equivalent), working with
  wired, USB-C and Bluetooth headphones and with the speaker. Flow `along` still asks for headphones.
- Recording timing has to be as exact as on the PC for Flow's slicing; this is checked on a real iPhone in M1.
- Screen stays on while practising.
- An interrupted take (phone call, another app's audio) is discarded, not scored.

### 4.5 Library, Review, Stats, Drills, Anki, Settings

Everything the PC has, with the same data and rules, laid out for a phone. Anki on a phone has no AnkiConnect, so:
- **Export to Anki**: the app writes an `.apkg` deck file (same note type and fields as the PC's listening cards) and
  hands it to the share sheet; AnkiMobile and AnkiDroid both import it.
- **Lessons from Anki**: the learner exports a deck from AnkiMobile/AnkiDroid as `.apkg`, opens it in our app, picks
  the fields as on the PC, and the app builds a lesson from the cards' sentences and audio.

### 4.6 Low-memory mode (phones with 4–6 GB)

The full set of models peaks at about 2 GB, which iOS and Android will not give an app on a 4 GB phone. On such
phones (detected from the device's total memory) the app never holds more than one large model at a time: for a take
it loads, runs and releases the recogniser, the aligner, the sounds model and the tone model in turn, and a lesson
build alternates the recogniser and the aligner per piece. Scores are the same; only time changes. Takes will take
longer (several seconds; M0 measures how many) and the app says "scoring…" for that long. Phones with 6 GB or more
use the normal mode. The builder may pick a better threshold from M0's measurements.

## 5. Voice profile and thresholds

Same as the PC: the tone model is speaker-independent; the pitch baseline is per install and blends in over the first
60 s of voiced speech. The sounds and gate thresholds stay as set on the PC (the user accepted this on 2026-11-07).
Phone microphones differ from PC ones: the gate thresholds (`min_rms_dbfs`, `min_align_conf`) are re-checked on the
iPhone in M1 and changed only if real takes are wrongly refused.

## 6. Phone screens

Portrait only, one hand. The PC's Lacquer style, colours and verdict colours carry over.

- **Bottom tab bar**: Library · Review · Stats · Settings. Drills open from Stats and Review, as on the PC.
- **Practice screen** (from the mockup the user saw on 2026-11-08):
  - top bar: back to Library, lesson title, sentence n / total, Echo | Flow switch;
  - the sentence (below);
  - the score (overall, tone, sounds) and the speaker/you pitch curves;
  - a bottom control bar in thumb reach: previous · Listen · Record/Stop · Me · next;
  - tapping a character opens its detail (tone or sound verdict, play the speaker's and your syllable).
- **Long sentences: clause by clause (option C, chosen by the user).**
  - The sentence is split at its commas and other clause punctuation.
  - While the speaker plays, the clause being spoken is large (about 34 px) and the clauses before and after stay
    small above and below. The large one moves on with the audio.
  - The learner still records the whole sentence in one go.
  - Results show the PC-style per-character cards for one clause at a time, with a score per clause. Swipe or tap a
    clause to switch.
  - Short sentences (one clause, or short enough to fit) show as one large block, no clause strip.
  - A clause too long for two lines at full size wraps between words, never inside one.
- **Flow**: the PC's Flow layout (passed lines dimmed with their score dot, the current line large, next lines
  smaller) in a phone column.
- **Library**: lesson list with sources (podcast, file, from PC), add-lesson sheet (search podcasts, paste feed,
  open file), build progress.
- Stats, Review, Drills, Settings: the PC's content stacked into one column; charts sized for the width.

The user's worry, kept as a check: long sentences must look good on a real phone, not just in a mockup. M1 tests
this with real podcast sentences on the iPhone, and the layout changes if they do not.

## 7. Testing on phones and sharing before the stores

- **iPhone**: a GitHub Actions workflow on a macOS runner builds, signs and uploads to TestFlight. The user installs
  TestFlight on the iPhone. Friends: TestFlight external testers (after Apple's short beta review).
- **Android**: the emulator on the PC for day-to-day work; the user's Motorola Edge 30 Neo (Snapdragon 695, 6 or 8 GB) for speed, memory, heat,
  Bluetooth delay and the score checks on real Android chips (from M0 on). Friends: the Play Console internal testing track (up to 100
  testers, no review) and then the 12-tester, 14-day closed test the first release needs.
- No sideloading and no jailbreak anywhere.

## 8. Same scores as the PC

The TypeScript port is checked against the Python app on the same inputs:
- the full set, from the user's real takes (the spike's 234 clean takes) with the Python app's results, runs **on the
  user's PC only**, read from the local data folder like the spike did. The user's voice and downloaded YouTube audio
  never go into the public repo (my call, following the repo privacy rules);
- CI runs the same checks on a small shareable set: synthetic and freely licensed speech, with the Python results
  generated from it and committed;
- per piece (pitch, alignment, enrichment, tone, sounds, words check, gates) and end to end;
- targets, from the spike's measured agreement: tone verdicts ≥ 98 %, sounds ≥ 97 %, pitch within 0.01 semitones,
  segment boundaries within 20 ms; the words check may differ on unclear speech (the user accepted this).

These run in CI in Node (with the native ONNX Runtime for Node) and again on the device in M0/M1.

## 9. What the feasibility spike measured (2026-11-08)

- Agreement with the PC app on 234 takes, 1,480 syllables: tone verdicts 98.6 %, heard tone 97.5 %, sounds 97.3 %
  (tone model fp32, others int8). All-int8 gave 92.5 % on tones, so the tone model stays fp32.
- iPhone 17, Safari, one core: tone model 0.9 s, each large model 4.0 s, recogniser 0.6 s per 4 s take. A PC core
  performs about the same in the browser, so the iPhone native is estimated from PC native: **a take ≈ 1.3–1.9 s of
  model time** (target ≤ 3 s) and **a 20-minute episode builds in ≈ 3.5–6 min** (target ≤ 10 min), more if the phone
  heats up.
- Memory natively: 1.3 GB with the four models loaded, about 2.0 GB peak (2.3 GB with the fp32 tone model).
- Not yet measured on a phone: memory, sustained heat, the native speed itself. M0 measures them.
- The Android test phone (Snapdragon 695: two fast cores, six slow ones) is much slower than the iPhone 17. A take
  there will probably take several seconds rather than under two; M0 measures it. Over the target there means
  midrange Android gets the app with slower scoring, not that Android is dropped (midrange is nice to have).
- Not yet checked at all: lesson building through ONNX. The spike compared only the recogniser's text, not its
  per-character timestamps, the VAD, or the PC's actual punctuation model (the small sherpa-onnx one in
  `ingest/punct.py`). M0 builds the same lessons on both and compares segment boundaries (§8 targets).
- The 1.3–1.9 s per take is model time only; pitch and the rest come on top (§4.2).

Spike files: `.superpowers/sdd/phone-spike/` (not in git).

## 10. Order of work

Each milestone ends with something the user can try on the iPhone or the emulator.

- **M0 – Proof on the phone.** Capacitor shell, the native model plugin, models bundled for testing, a hidden screen
  that scores a canned take and builds a 5-minute lesson. Android first (emulator and the Motorola over USB, free);
  once that works the user buys the Apple membership and the same build goes to the iPhone through TestFlight. Measure speed (including pitch), peak memory and heat on the
  iPhone (TestFlight), the real Android phone and the emulator, in both normal and low-memory mode (a 4 GB phone if
  one can be borrowed; otherwise memory capped by hand). On the PC: build the same lessons with the ONNX models and the Python app and
  compare segment boundaries. **Stop and report if memory or speed fails the targets.**
- **M1 – Echo and Flow with PC lessons.** PC "Export lesson"; phone import; the TypeScript scoring path with the parity
  tests; Echo and Flow on the phone layout with clause-by-clause sentences. Tested on the Android emulator first, then
  the iPhone.
- **M2 – Lessons made on the phone.** The TypeScript building path; own files; podcasts.
- **M3 – Everything else.** Library polish, Review, Stats, Drills, Anki (.apkg out and in), Settings; model download on
  first launch.
- **M4 – Store release.** The user's decisions on the seller name and the App Store licence exception (§3); model
  licences checked and models hosted; store listings, screenshots and privacy labels;
  TestFlight external testers; Play closed test (12 testers, 14 days); release.

## 11. Calls I made (for the user to check)

- Capacitor + native ONNX Runtime + TypeScript port (§4.1).
- Models downloaded on first launch, hosted on GitHub Releases (§4.2).
- No podcast subscriptions or auto-download in the first release (§4.3).
- Anki through `.apkg` files both ways (§4.5).
- Bottom tab bar and portrait only (§6).
- Lessons from the PC as an exported file, not by sync (§4.3).
- Low-memory mode: one large model at a time, switched on below 6 GB of device memory (§4.6).
- The full score check against the user's own takes runs on the PC only, never in the public repo (§8).
- Pitch ported from the published algorithm, not Praat's GPL source; moved to native code if TypeScript is too slow
  (§4.2).

## 12. Left to the builder

- The exact TypeScript equivalents for jieba, pypinyin and OpenCC, as long as §8's checks pass.
- The SQLite plugin, the podcast search API details, the `.apkg` reader/writer.
- How building keeps running with the screen locked on each OS.
- The export file's exact layout.
- Whether the PC's 4 s "warm-up" logic and caches (reference embeddings, emissions reuse) carry over as they are.
