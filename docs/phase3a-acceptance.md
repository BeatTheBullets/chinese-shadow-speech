# Phase 3a acceptance — wrong sounds

- [ ] Say 吃 as cī in Echo. The HEARD row shows `cī` under 吃, 吃 is ringed (purple) in the reference row, and the header chip reads "1 sound off".
- [ ] A clean take shows no HEARD row and the chip reads "sounds ok".
- [ ] Clicking a You cell plays that syllable (a missing or unvoiced one plays nothing).
- [ ] Stats shows a Sounds panel. **Drill this** starts a sound drill whose item goes green when the sound is right, even if a tone is orange.
- [ ] Playback of your take starts at your voice, not at the silence before it: **R**, and the automatic reference → you playback in Echo.
- [ ] A too-quiet take shows its warning and leaves no take behind (no new take on reopening the lesson, none in Stats).
- [ ] `curl -s localhost:8000/health` lists `sounds`, and `sounds_error` is null.
- [ ] Older takes: `make backfill-sounds ARGS=--dry-run` reports counts and writes nothing. Back up `data/shadow.db`, stop the backend, then run `make backfill-sounds`. Every scored take is done or explicitly skipped.
- [ ] Optional: `cd backend && uv run python scripts/drop_failed_takes.py --dry-run` counts old takes the recording gates rejected. Run it without `--dry-run` to remove them.
- [ ] VRAM and RAM stay usable while gaming. After a few takes and an import: `nvidia-smi`, `free -m`, and the backend process RSS (`ps -o rss= -p <pid>`) stays around 1.8 GB with all models loaded, not 5 GB or more.
