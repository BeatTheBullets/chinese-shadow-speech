# Phase 1 acceptance (manual, Brave on Windows, backend in WSL)

Items 1-8 are the checks automated tests and reviewers could not run; do them first.

## Real hardware and real data

- [ ] Upload a real recording: the tile shows the live stage bar, then the lesson is ready with N sentences. `curl localhost:8000/health` shows device `cuda` (the driver must support CUDA 12.6) and the loaded models after first use.
- [ ] First real ingest: run `cd backend && uv run pytest -m models` once after `uv sync --extra dev --extra models`.
- [ ] Echo with a real mic: the permission prompt appears, VAD auto-stops the take, and a denied mic shows a readable error.
- [ ] Syllable cell click plays the right syllable once; clicking again plays it again (seek accuracy).
- [ ] Flow: run several sentences, stop midway, then `GET /segments/{id}/attempts` shows slices aligned with what was said.
- [ ] Anki import: check one real asbplayer note's Source field format (lesson grouping depends on it; the parser accepts `name_123`-style suffixes and `(1h2m3s)` timestamps, but the real format was never verified), and that the first `[sound:]` clip is used.
- [ ] Anki export: a real note with playable audio; edit a sentence, reload the page, export again, and confirm the new audio (not a cached old clip).
- [ ] Docker (optional): `docker compose up --build` after `npm run build`.

## Feature checklist

- [ ] Upload a 5-10 min Mandarin video: tile shows stages normalise, transcribe, rectify, align, enrich; lesson ready with 6-25-char sentences; clips start/end cleanly.
- [ ] Upload the same video with its .srt: sentences follow the subtitles.
- [ ] Upload it again with the .srt shifted by a few seconds (or from a release with a different intro): clips still start and end on the spoken sentences.
- [ ] Upload it with a plain-text transcript (.txt, one line per sentence or paragraph): the lesson's text is the transcript's, not the ASR's.
- [ ] Upload it with another episode's subtitles: the lesson shows a readable "subtitles don't match the audio (NN % of characters matched)" note and uses the ASR text.
- [ ] Anki import: Settings, Connect, add query, Library, refresh: one lesson per source video; re-import adds only new notes.
- [ ] Configure two import queries that share a video (e.g. `deck:Mining tag:asbplayer` and `rated:1`) and run both: one lesson for that video, no duplicate sentences.
- [ ] Restart the backend during an ingest (Ctrl-C, or save a backend file under `make dev`): the tile shows an "interrupted" error you can delete, not a perpetual job.
- [ ] Library tile ✎ renames title and speaker (the tile moves to the new speaker group); ✕ asks, then deletes the lesson.
- [ ] Yomitan: with pinyin ON, hovering 今天 shows the CC-CEDICT entry for the two-character word, not 今 alone; same with pinyin OFF.
- [ ] Echo: Space / Enter / silence stop / back-to-back playback / You track waveform and cells.
- [ ] Chorus: 5 passes, last pass recorded, one attempt with mode chorus.
- [ ] Flow (after): continuous, dots fill in, summary with play ref+you per line; stopping mid-run keeps finished lines.
- [ ] Flow (along) with headphones: recordings contain only your voice.
- [ ] Guided: listen, whisper (text visible), record (text hidden), next.
- [ ] Toggles T/P/E persist per lesson after reload; text hides while recording; drawer collapses with L.
- [ ] Timer turns amber at 20:00; "move on" hint after 4 attempts.
- [ ] Edit text: cells and clip update; split and merge; flag shows in drawer and Review.
- [ ] Review: flagged sentences listed oldest lesson first; Practise opens the lesson on that sentence.
- [ ] A -> Anki creates a note with playable mp3; Review, "A -> Anki all".
- [ ] Stats, Activity shows today's minutes and attempts; the other panels show "No scores yet" in Phase 1.
- [ ] Production build: `cd frontend && npm run build`, start the backend, open `http://127.0.0.1:8000/library`; deep links such as `/practice/1` load.

## Phase 1.5: YouTube, passages, guidance, listening cards (manual)

- [ ] Aligner: the MMS_FA comparison ran on lesson 1 and its verdict is in the plan ledger (`docs/superpowers/plans/2026-10-07-youtube-passages-guidance.md`); after re-ingesting lesson 1, clips no longer start a second early and syllable clicks play the right syllable.
- [ ] A real YouTube video with Chinese subtitles: paste the link in the Library; the tile shows the `download` stage, then the lesson has the video's title and channel (simplified) and the subtitle text.
- [ ] A real YouTube video without Chinese subtitles: the lesson uses the ASR text.
- [ ] A video that needs sign-in (age-restricted): without `[youtube] cookies_file` the tile shows "this video needs a cookies file — see Settings" and can be deleted; with a cookies file it ingests.
- [ ] Brave bookmarklet: drag "→ chinese-shadow-speech" from Settings to the bookmarks bar, click it on a YouTube video: the app asks "Add … to chinese-shadow-speech?", adds it, and the address bar shows `/library` without `?add=`. Adding the same video again creates no second lesson.
- [ ] A video with chapters: passages are named after the chapters; a long video without chapters has "Passage N · mm:ss–mm:ss" passages of about 2–3 minutes.
- [ ] Practice: "Passage 4 / 9" in the top bar jumps between passages; Flow's range defaults to the current passage; the drawer groups sentences under passage headers with ✓ once every sentence has an attempt; the library tile shows "n / m passages".
- [ ] Help: the overlay opens on the first visit only; `?` opens and closes it, Esc closes it; hovering a mode tab shows its description.
- [ ] Cue line: says Listen / Your turn — speak now / Speak along / Ready / Done at the right moments in every mode; the mic meter moves when you speak.
- [ ] Yomitan over a wiping sentence: during reference playback, hover 今天: the popup shows the two-character word, with pinyin on and off.
- [ ] Karaoke: the sentence colours in sync with the audio; in Echo the count-in dots then the amber ghost wipe run while you record; in Flow after the turn bar shrinks over the pause; in Flow along the next line is shown dimmed below the current one.
- [ ] Volume: the reference volume slider changes playback and survives a reload; in Flow along and Chorus the guide level is audibly quieter than the reference volume and adjustable live; your own takes play at the reference volume; the headphones hint appears once.
- [ ] Anki: Settings → "Set up chinese-shadow-speech deck" creates the deck and the "Shadow Listening" note type (or reuses them); a listening card's front plays the audio and asks "What did you hear?"; its back shows the sentence, pinyin, translation and the Source link opening the video at the right second.
- [ ] Session end: "Finish session", closing the Flow summary and the ← link offer this session's practised sentences with fillers unticked; with Anki closed each row shows an error and the sentences are listed in Review → "Practised, not in Anki", from where they can be sent later.

Browser-only checks the automated tests cannot make (jsdom has no layout, no real audio and no extensions):

- [ ] Karaoke wipe on the glyphs: the colour wipe sits exactly on the characters, with pinyin on and off, including a long sentence that wraps onto two lines (the wipe follows the second line, not a straight bar across the first).
- [ ] Yomitan while the wipe runs: the hover popup appears over the wiping sentence (the wipe layer never takes the mouse), and selecting text in it still works.
- [ ] Lesson 1 re-ingested with the default aligner (`auto` → MMS_FA, with alignment repair): clicking the first syllable of several sentences plays that syllable, not the tail of the previous sentence or silence.
- [ ] YouTube: a real video with Chinese subtitles and one without both ingest; a video that needs cookies fails with the cookies message until `[youtube] cookies_file` is set; with Deno off the PATH a video that needs it fails with "install Deno (https://deno.com) — yt-dlp needs it for YouTube", and ingests once Deno is installed.
- [ ] Shadow Listening card in Anki: the front has only the audio and "What did you hear?" (no sentence text); the back has the sentence, pinyin, translation, Source and a Link that opens the video at the sentence. A lesson whose title contains `<` or `&` (rename one in the Library) shows the title literally in Source, not as broken HTML.
- [ ] ← link: Ctrl-click (Cmd-click on macOS) and middle-click open the library in a new tab with no dialog; a plain click during a Flow run stops the run, keeps its finished sentences (they appear with an attempt) and then offers them.
- [ ] No double send: while the session-end dialog is sending, Close is greyed out and Esc does nothing; in Review, "A → Anki all" and the "Practised, not in Anki" list never send at the same time, and a sentence sent by one shows as sent ✓ in the other.
