# Phase 1 acceptance (manual, Brave on Windows, backend in WSL)

Items 1-8 are the checks automated tests and reviewers could not run; do them first.

## Real hardware and real data

- [ ] Upload a real recording: the tile shows the live stage bar, then the lesson is ready with N sentences. `curl localhost:8000/health` shows device `cuda` (the driver must support CUDA 12.6) and the loaded models after first use.
- [ ] First real ingest: run `cd backend && uv run pytest -m models` once after `uv sync --extra dev --extra models`.
- [ ] Echo with a real mic: the permission prompt appears, VAD auto-stops the take, and a denied mic shows a readable error.
- [ ] Syllable cell click loops the right syllable (seek accuracy).
- [ ] Flow: run several sentences, stop midway, then `GET /segments/{id}/attempts` shows slices aligned with what was said.
- [ ] Anki import: check one real asbplayer note's Source field format (lesson grouping depends on it; the parser accepts `name_123`-style suffixes and `(1h2m3s)` timestamps, but the real format was never verified), and that the first `[sound:]` clip is used.
- [ ] Anki export: a real note with playable audio; edit a sentence, reload the page, export again, and confirm the new audio (not a cached old clip).
- [ ] Docker (optional): `docker compose up --build` after `npm run build`.

## Feature checklist

- [ ] Upload a 5-10 min Mandarin video: tile shows stages normalise, transcribe, rectify, align, enrich; lesson ready with 6-25-char sentences; clips start/end cleanly.
- [ ] Upload the same video with its .srt: sentences follow the subtitles.
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
