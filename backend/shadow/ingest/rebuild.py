"""Rebuild an existing lesson's text: re-transcribe its audio and cut its sentences again, keeping its takes."""
from __future__ import annotations
import logging
from pathlib import Path
from sqlalchemy import Engine
from sqlmodel import Session, select
from shadow.deps import Deps
from shadow.ingest import audio
from shadow.ingest.passages import rebuild_passages
from shadow.ingest.pipeline import (NoSpeechError, _has_speech, _merge_meta, _set_status, _subtitle_transcript,
                                    build_segments)
from shadow.ingest.rectify import rectify_transcript
from shadow.ingest.reenrich import renumber
from shadow.ingest.transcript import Transcript
from shadow.jobs import Progress
from shadow.scoring import score_attempt
from shadow.scoring.profile import get_profile
from shadow.store.models import Attempt, Lesson, Segment, SyllableScore

log = logging.getLogger(__name__)
# meta_json key while a rebuild runs: {"offset": idx of the first new segment, "swapped": bool}, so that a restart
# mid-rebuild (no job survives one) can put the lesson back together (`recover_rebuild`)
REBUILD = "rebuild"


def match_segment(start: float, end: float, new: list[tuple[int, float, float]]) -> int:
    """Id of the new segment (`new`: (id, start_s, end_s) in idx order) that takes over an old one spanning
    [start, end]: the one it overlaps most (ties: the earlier), or, overlapping none, the one whose midpoint is
    nearest its own (ties: the earlier)."""
    overlaps = [min(end, b) - max(start, a) for _, a, b in new]
    if max(overlaps) > 0:
        return new[overlaps.index(max(overlaps))][0]
    mid = (start + end) / 2
    dist = [abs((a + b) / 2 - mid) for _, a, b in new]
    return new[dist.index(min(dist))][0]


def _subtitle_text(lesson: Lesson) -> tuple[str, str] | None:
    """The subtitle text ingest used, as a plain-text "subtitle" (one line per cue), or None for an ASR lesson. It is
    not stored as such (YouTube subtitles are downloaded, uploaded ones discarded), but the transcript of a subtitle
    lesson is its text with one segment per cue (align_text_to_asr), and only its times came from the drifted ASR."""
    if "subtitle_match" not in (lesson.meta_json or {}) or not lesson.transcript_json:
        return None
    tr = Transcript.from_json(lesson.transcript_json)
    return "transcript.txt", "\n".join("".join(c.c for c in tr.chars[a:b + 1]) for a, b in tr.segments)


def _unlink_clips(deps: Deps, lesson_id: int, idxs: list[int]) -> None:
    for i in idxs:
        for p in (deps.files.clip_wav(lesson_id, i), deps.files.clip_opus(lesson_id, i), deps.files.clip_mp3(lesson_id, i)):
            p.unlink(missing_ok=True)


def _swap(deps: Deps, engine: Engine, lesson_id: int, offset: int, tr: Transcript) -> list[int]:
    """One transaction: every old segment (idx < `offset`) hands its takes, difficulty flag and Anki note to the new
    segment (idx >= `offset`) it matches in time, the old segments and their syllable rows go, the lesson gets the new
    transcript and loses its cached pitch baseline (the clips changed), and its rebuild marker says the swap is done.
    Returns the moved attempts' ids; the old clip
    files are removed after the commit."""
    with Session(engine) as db:
        lesson = db.get(Lesson, lesson_id)
        if lesson is None:
            return []
        segs = db.exec(select(Segment).where(Segment.lesson_id == lesson_id).order_by(Segment.idx)).all()
        olds, news = [s for s in segs if s.idx < offset], [s for s in segs if s.idx >= offset]
        by_id = {s.id: s for s in news}
        spans = [(s.id, s.start_s, s.end_s) for s in news]
        moved: list[int] = []
        for old in olds:
            target = by_id[match_segment(old.start_s, old.end_s, spans)]
            target.difficulty_flag = target.difficulty_flag or old.difficulty_flag
            if old.anki_note_id is not None and old.anki_note_id != target.anki_note_id:
                if target.anki_note_id is None:
                    target.anki_note_id = old.anki_note_id
                else:
                    log.warning("lesson %d: sentence %d's Anki note %d is dropped; %r keeps note %d", lesson_id,
                                old.idx, old.anki_note_id, target.text, target.anki_note_id)
            db.add(target)
            for a in db.exec(select(Attempt).where(Attempt.segment_id == old.id)).all():
                a.segment_id = target.id
                db.add(a); moved.append(a.id)
        old_ids = [s.id for s in olds]
        for row in db.exec(select(SyllableScore).where(SyllableScore.segment_id.in_(old_ids))).all():
            db.delete(row)                         # scored against the old text: re-scored below
        db.flush()
        for s in olds:
            db.delete(s)
        old_idxs = [s.idx for s in olds]          # read before the commit expires the deleted rows
        lesson.transcript_json = tr.to_json()
        meta = {k: v for k, v in (lesson.meta_json or {}).items() if k != "pitch"}
        lesson.meta_json = {**meta, REBUILD: {"offset": offset, "swapped": True}}
        db.add(lesson); db.commit()
    _unlink_clips(deps, lesson_id, old_idxs)
    return moved


def _drop_meta(engine: Engine, lesson_id: int, *keys: str) -> None:
    with Session(engine) as db:
        lesson = db.get(Lesson, lesson_id)
        if lesson is None:
            return
        lesson.meta_json = {k: v for k, v in (lesson.meta_json or {}).items() if k not in keys}
        db.add(lesson); db.commit()


def _discard_new(deps: Deps, engine: Engine, lesson_id: int, offset: int) -> None:
    """Undo a rebuild that failed before the swap: its new segments (idx >= `offset`) and clip files go."""
    with Session(engine) as db:
        for s in db.exec(select(Segment).where(Segment.lesson_id == lesson_id, Segment.idx >= offset)).all():
            db.delete(s)
        db.commit()
    clips = deps.files.clip_wav(lesson_id, 0).parent
    _unlink_clips(deps, lesson_id, sorted({int(p.stem) for p in clips.glob("*.*")
                                           if p.stem.isdigit() and int(p.stem) >= offset}))


def _rescore(deps: Deps, engine: Engine, attempt_ids: list[int], progress: Progress) -> None:
    """Score the moved takes again, oldest first, against their new sentences. Their pitch is already in the voice
    profile (from their first scoring), so the profile is put back as it was afterwards rather than fed twice. A take
    whose audio is gone keeps its old score_json (its syllable rows are gone with its old sentence)."""
    progress("rescore", 0.0)
    with Session(engine) as db:
        p = get_profile(db)
        saved = None if p.id is None else (list(p.frames_json or []), p.baseline_hz, p.spread_st, p.voiced_s, p.updated_at)
        atts = db.exec(select(Attempt).where(Attempt.id.in_(attempt_ids)).order_by(Attempt.created_at, Attempt.id)).all()
        order = [a.id for a in atts]
    for n, aid in enumerate(order):
        with Session(engine) as db:
            att = db.get(Attempt, aid)
            if att is not None and att.audio_path and Path(att.audio_path).exists():
                score_attempt(deps, db, db.get(Segment, att.segment_id), att)
                db.add(att); db.commit()
            else:
                log.warning("attempt %d has no audio; keeping its old score", aid)
        progress("rescore", (n + 1) / len(order))
    with Session(engine) as db:
        p = get_profile(db)
        if saved is None:
            if p.id is not None:
                db.delete(p)
        else:
            p.frames_json, p.baseline_hz, p.spread_st, p.voiced_s, p.updated_at = saved
            db.add(p)
        db.commit()


def rebuild_lesson(deps: Deps, engine: Engine, lesson_id: int, progress: Progress) -> None:
    """Re-transcribe the lesson's source audio and rebuild its sentences, words, clips and passages as ingest does
    (a subtitle lesson keeps its subtitle text, re-timed from the new transcript). The new segments are written
    after the old ones (idx from `offset`), so until the swap the old lesson is intact and a failure discards only
    the new rows and clips; then the takes move over by time (`_swap`), idx becomes dense again and the moved takes
    are re-scored. The lesson is `processing` meanwhile (the API sets it); afterwards `ready`, also after a failure
    when it has segments (the job carries the error), else `error`."""
    offset = 0
    swapped = False
    try:
        with Session(engine) as db:
            lesson = db.get(Lesson, lesson_id)
            if lesson is None:
                return
            subtitle = _subtitle_text(lesson)
            idxs = db.exec(select(Segment.idx).where(Segment.lesson_id == lesson_id)).all()
            offset = max(idxs, default=-1) + 1
        _set_status(engine, lesson_id, "processing")
        _merge_meta(engine, lesson_id, **{REBUILD: {"offset": offset, "swapped": False}})
        source_wav = deps.files.source_wav(lesson_id)
        progress("transcribe", 0.0)
        tr = deps.asr.transcribe(source_wav)
        if not _has_speech(tr):
            raise NoSpeechError("no speech found in the recording")
        if subtitle is not None:
            sub_tr, meta = _subtitle_transcript(subtitle, tr)
            _merge_meta(engine, lesson_id, **meta)
            if sub_tr is not None:
                tr = sub_tr
            else:                                  # the ASR text replaces the subtitles' from now on
                _drop_meta(engine, lesson_id, "subtitle_match")
        progress("transcribe", 1.0)

        progress("rectify", 0.0)
        sentences = rectify_transcript(tr)
        progress("rectify", 1.0)

        build_segments(deps, engine, lesson_id, source_wav, tr, sentences, progress, idx_offset=offset)
        progress("clips", 0.0)
        moved = _swap(deps, engine, lesson_id, offset, tr)
        swapped = True
        renumber(deps, engine, lesson_id)
        rebuild_passages(engine, lesson_id)
        progress("clips", 1.0)
        _rescore(deps, engine, moved, progress)
        _drop_meta(engine, lesson_id, REBUILD)
        _set_status(engine, lesson_id, "ready", duration_s=audio.duration_s(source_wav))
        progress("done", 1.0)
    except Exception as e:  # noqa: BLE001
        try:
            if not swapped:
                _discard_new(deps, engine, lesson_id, offset)
            _drop_meta(engine, lesson_id, REBUILD)
        except Exception:  # noqa: BLE001  the lesson must not stay `processing`; the job reports the first error
            log.exception("lesson %d: cleaning up after a failed rebuild failed", lesson_id)
        _finish(engine, lesson_id, str(e) or type(e).__name__)
        raise


def _finish(engine: Engine, lesson_id: int, error: str) -> None:
    """`ready` when the lesson has segments (old or new, each set consistent on its own), else `error`."""
    with Session(engine) as db:
        has_segments = db.exec(select(Segment.id).where(Segment.lesson_id == lesson_id)).first() is not None
    _set_status(engine, lesson_id, "ready" if has_segments else "error", None if has_segments else error)


def recover_rebuild(deps: Deps, engine: Engine, lesson_id: int) -> None:
    """After a restart killed a rebuild of this lesson (its meta still holds the REBUILD marker): before the swap the
    new segments (idx >= offset) sit beside the old ones and are dropped with their clips; after it only renumbering
    and passages may be missing, so they are redone. The moved takes keep the scores they had (`make rescore`
    re-scores them)."""
    with Session(engine) as db:
        lesson = db.get(Lesson, lesson_id)
        mark = (lesson.meta_json or {}).get(REBUILD) if lesson is not None else None
    if not mark:
        return
    if mark.get("swapped"):
        renumber(deps, engine, lesson_id)
        rebuild_passages(engine, lesson_id)
    else:
        _discard_new(deps, engine, lesson_id, int(mark["offset"]))
    _drop_meta(engine, lesson_id, REBUILD)
