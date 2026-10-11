# Phase 2 acceptance — tone scoring

- [ ] `/health` shows `tone_model.loaded: true` and the version from the ledger.
- [ ] Echo a sentence you know well: most cells green, a score in the header, two pitch lines on the You track.
- [ ] Echo the same sentence with one tone deliberately wrong (e.g. say 好 rising): that cell turns red and shows `3→2` (or orange), the others stay green.
- [ ] Say a different sentence than the one shown: mostly red/orange cells and a low score (possibly "Could not match this to the sentence — not scored."; the gate cannot catch most wrong sentences, see the plan ledger, Task 15).
- [ ] Whisper or record from across the room: "Too quiet — not scored."
- [ ] Reopen the lesson: the last take's colours and pitch lines come back.
- [ ] Flow a passage: rows take a colour as their slices are scored; the summary shows a mean and the weakest lines.
- [ ] Stats: tone means, the weekly chart, the tone-pair matrix (3-3 cells after a sandhi-heavy lesson) and the weakest characters.
- [ ] Settings → Voice profile shows your baseline; Reset empties it and the next takes rebuild it.
- [ ] Skim `data/reports/rescore-<date>.html`: red cells land where the take sounds wrong.
- [ ] `cd backend && ~/.local/bin/uv run pytest -m models -q` passes.
