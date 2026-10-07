from __future__ import annotations
import base64
import binascii
import logging
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
import numpy as np
from pydantic import BaseModel
from sqlalchemy import Engine
from sqlmodel import Session, select
from shadow.deps import Deps
from shadow.ingest import audio
from shadow.ingest.pipeline import MIN_CLIP_S, _merge_meta, _set_status, build_segments
from shadow.ingest.rectify import RectSentenceOut
from shadow.ingest.text import strip_html, to_simplified
from shadow.jobs import Progress
from shadow.store.models import Lesson, Segment

log = logging.getLogger(__name__)

GAP_S = 0.5     # silence between consecutive clips in the concatenated source.wav
_SOUND = re.compile(r"\[sound:[^\]]*\]")
# Trailing timestamp of asbplayer's Source field: "<name> [h:]mm:ss.mmm", or "<name> (00h00m08.3s)" (its default,
# zero-padded with a tenth of a second) / "(1h02m03s)" / "(2m03s)" / "(45s)" (its edit dialog).
_TS = re.compile(r"\s+(?:(\d{1,2}):)?(\d{1,2}):(\d{2})[.,](\d{3})$")
_TS_HMS = re.compile(r"\s*\((?:(\d+)h)?(?:(\d+)m)?(\d+(?:\.\d+)?)s\)$")


class AnkiNoteIn(BaseModel):
    note_id: int
    text: str
    translation: str | None = None
    source: str | None = None
    url: str | None = None
    audio_b64: str
    filename: str


def parse_source(source: str | None) -> tuple[str, float | None]:
    """(video name, timestamp in seconds or None) from an asbplayer Source field."""
    if not source:
        return "", None
    s = strip_html(source)
    m = _TS.search(s)
    if m:
        h, mi, se, ms = (int(x or 0) for x in m.groups())
        return s[: m.start()].strip(), h * 3600 + mi * 60 + se + ms / 1000
    m = _TS_HMS.search(s)
    if m:
        h, mi, se = int(m.group(1) or 0), int(m.group(2) or 0), float(m.group(3))
        return s[: m.start()].strip(), h * 3600 + mi * 60 + se
    return s.strip(), None


def clean_sentence(text: str) -> str:
    return to_simplified(strip_html(_SOUND.sub("", text))).strip()


def group_by_video(notes: list[AnkiNoteIn]) -> dict[str, list[AnkiNoteIn]]:
    groups: dict[str, list[AnkiNoteIn]] = defaultdict(list)
    for n in notes:
        groups[parse_source(n.source)[0]].append(n)
    for g in groups.values():
        g.sort(key=lambda n: (parse_source(n.source)[1] or 0.0, n.note_id))
    return dict(groups)


def existing_note_ids(engine: Engine, lesson_id: int) -> set[int]:
    with Session(engine) as db:
        rows = db.exec(select(Segment.anki_note_id).where(Segment.lesson_id == lesson_id)).all()
        return {r for r in rows if r is not None}


def skipped_notes(engine: Engine, lesson_id: int) -> dict[str, str]:
    """{note_id: reason} of notes the lesson could not use (lesson.meta_json["skipped_notes"]; JSON keys are str)."""
    with Session(engine) as db:
        lesson = db.get(Lesson, lesson_id)               # None if deleted while a job runs
        return dict(((lesson.meta_json if lesson else None) or {}).get("skipped_notes", {}))


def handled_note_ids(engine: Engine, lesson_id: int) -> set[int]:
    """Notes a re-import need not look at again: already segments, or skipped as unusable."""
    return existing_note_ids(engine, lesson_id) | {int(k) for k in skipped_notes(engine, lesson_id)}


def is_importable(note: AnkiNoteIn) -> bool:
    return bool(clean_sentence(note.text))


def _decode_clip(note: AnkiNoteIn, tmp: Path) -> np.ndarray:
    """The note's clip as 16 kHz mono samples; RuntimeError if it cannot be decoded."""
    try:
        data = base64.b64decode(note.audio_b64, validate=True)
        if not data:
            raise RuntimeError("no audio")
        raw, norm = tmp / f"{note.note_id}_{Path(note.filename).name}", tmp / f"{note.note_id}.wav"
        raw.write_bytes(data)
        audio.normalise(raw, norm)
        return audio.read_wav(norm)[0]
    except (binascii.Error, subprocess.CalledProcessError, RuntimeError) as e:
        raise RuntimeError(f"audio of note {note.note_id} could not be decoded") from e


def ingest_anki_group(deps: Deps, engine: Engine, lesson_id: int, notes: list[AnkiNoteIn], progress: Progress) -> None:
    """Append `notes` (one source video) to the lesson: each note's own clip is the reference audio, so the clips
    are concatenated into source.wav with GAP_S of silence between them and each becomes a segment spanning
    exactly its clip. Anki lessons keep no transcript (spec §4). A note with no text, no decodable audio or a
    too-short clip is skipped on its own (logged, recorded in meta_json["skipped_notes"]); the lesson errors only
    if it ends up with no segments at all."""
    tmp = deps.files.lesson_dir(lesson_id) / "anki_tmp"
    try:
        _set_status(engine, lesson_id, "processing")
        progress("normalise", 0.0)
        with Session(engine) as db:
            start_idx = len(db.exec(select(Segment.id).where(Segment.lesson_id == lesson_id)).all())
        seen = handled_note_ids(engine, lesson_id)        # also guards against two overlapping imports
        source_wav = deps.files.source_wav(lesson_id)
        pieces = [audio.read_wav(source_wav)[0]] if source_wav.exists() else []
        pos = sum(len(p) for p in pieces)                 # samples already in source.wav
        gap = np.zeros(int(GAP_S * audio.SR), dtype="float32")
        tmp.mkdir(parents=True, exist_ok=True)
        sentences: list[RectSentenceOut] = []
        note_ids: list[int] = []
        spans: list[tuple[float, float]] = []
        translations: list[str | None] = []
        skipped: dict[str, str] = {}
        for i, n in enumerate(notes):
            if n.note_id not in seen:
                seen.add(n.note_id)
                text = clean_sentence(n.text)
                try:
                    if not text:
                        raise RuntimeError("empty text")
                    clip = _decode_clip(n, tmp)
                    if len(clip) / audio.SR < MIN_CLIP_S:
                        raise RuntimeError("audio too short")
                except RuntimeError as e:
                    log.warning("skipping Anki note %d: %s", n.note_id, e)
                    skipped[str(n.note_id)] = str(e)
                else:
                    if pos:
                        pieces.append(gap); pos += len(gap)
                    spans.append((pos / audio.SR, (pos + len(clip)) / audio.SR))
                    pieces.append(clip); pos += len(clip)
                    sentences.append(RectSentenceOut(0, 0, text))     # char range unused with fixed spans
                    note_ids.append(n.note_id)
                    translations.append(to_simplified(strip_html(n.translation or "")) or None)
            progress("normalise", (i + 1) / len(notes))
        if skipped:
            _merge_meta(engine, lesson_id, skipped_notes={**skipped_notes(engine, lesson_id), **skipped})
        if sentences:
            audio.write_wav(source_wav, np.concatenate(pieces))
            build_segments(deps, engine, lesson_id, source_wav, None, sentences, progress,
                           anki_note_ids=note_ids, idx_offset=start_idx, fixed_spans=spans, translations=translations)
        elif start_idx == 0:
            raise RuntimeError("no usable notes: " + "; ".join(f"{k}: {v}" for k, v in skipped.items()))
        _set_status(engine, lesson_id, "ready", duration_s=pos / audio.SR)
        progress("done", 1.0)
    except Exception as e:  # noqa: BLE001
        _set_status(engine, lesson_id, "error", error=str(e) or type(e).__name__)
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
