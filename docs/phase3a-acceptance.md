# Phase 3a acceptance — wrong sounds

## Data first (in this order)

1. [ ] Back up `data/shadow.db` (e.g. `cp data/shadow.db data/shadow.db.pre-3a`).
2. [ ] Stop the backend.
3. [ ] Back-fill older takes: `make backfill-sounds ARGS=--dry-run` reports counts and writes nothing (it opens the
   database read-only). Then run `make backfill-sounds`. Every scored take is done or explicitly skipped.
4. [ ] Old takes the recording gates rejected: `cd backend && uv run python scripts/drop_failed_takes.py --dry-run`
   counts them; then run it without `--dry-run` to remove them. It deletes audio files, which a DB backup does not
   restore — copy `data/attempts/` too if you want them back.
5. [ ] Restart the backend. While it warms up, note the RAM peak (`free -m`, and the backend RSS with
   `ps -o rss= -p <pid>`, every few seconds until `/health` lists `sounds`).

## Stats and Drill

- [ ] `curl -s localhost:8000/health` lists `sounds` once warm-up has finished (about a minute after start), and
  `sounds_error` is null.
- [ ] Stats shows a Sounds panel. **Drill this** starts a sound drill whose item goes green when the sound is right,
  even if a tone is orange.
- [ ] An `ng>n` drill offers no 定/顶/丁 targets (ding's partner din is never checked, so it could never go green).

## Practice

- [ ] Say 吃 as cī in Echo. The HEARD row shows `cī` under 吃, 吃 is ringed (purple) in the reference row, and the
  header chip reads "1 sound off".
- [ ] A clean take shows no HEARD row and the chip reads "sounds ok".
- [ ] Clicking a You cell plays that syllable (a missing or unvoiced one plays nothing).
- [ ] Playback of your take starts at your voice, not at the silence before it: **R**, and the automatic reference →
  you playback in Echo.
- [ ] A too-quiet take shows its warning and leaves no take behind (no new take on reopening the lesson, none in Stats).
  Note: after a dropped take, the You track shows your previous stored take for that sentence, if there is one.

## Memory

- [ ] Startup peak (step 5 above) noted: ____ MB.
- [ ] VRAM and RAM stay usable while gaming. After a few takes and an import (the steady state): `nvidia-smi`,
  `free -m`, and the backend process RSS (`ps -o rss= -p <pid>`) stays around 1.8 GB with all models loaded, not 5 GB
  or more.
