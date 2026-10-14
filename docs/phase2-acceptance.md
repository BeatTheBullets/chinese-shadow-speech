# Phase 2 acceptance — tone scoring

- [ ] `/health` shows `tone_model.loaded: true` and the version from the ledger.
- [ ] Echo a sentence you know well: most cells green, a score in the header, two pitch lines on the You track.
- [ ] Echo the same sentence with one tone deliberately wrong (e.g. say 好 rising): that cell turns red and shows `3→2` (or orange), the others stay green.
- [ ] Say a different sentence than the one shown (one that shares few words with it): "Heard different words — not scored. Heard: …" with what you said, and no cell colours. A sentence sharing most of its words can still pass and be scored.
- [ ] Say the sentence with one or two words swapped or mumbled: the take is scored (cells and a score in the header) and the hint says "Some words sounded different — heard: …".
- [ ] Whisper or record from across the room: "Too quiet — not scored."
- [ ] Reopen the lesson: the last take's colours and pitch lines come back.
- [ ] Flow a passage: rows take a colour as their slices are scored; the summary shows a mean and the weakest lines.
- [ ] Stats: tone means, the weekly chart, the tone-pair matrix (3-3 cells after a sandhi-heavy lesson) and the weakest characters.
- [ ] Settings → Voice profile shows your baseline; Reset empties it and the next takes rebuild it.
- [ ] Skim `data/reports/rescore-<date>.html`: red cells land where the take sounds wrong.
- [ ] `cd backend && ~/.local/bin/uv run pytest -m models -q` passes.
