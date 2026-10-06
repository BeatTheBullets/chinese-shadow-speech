from __future__ import annotations
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import Session, select
from shadow.api.lessons import _segment_out
from shadow.ingest import audio
from shadow.ingest.pipeline import MIN_CLIP_S
from shadow.ingest.reenrich import reenrich_segment, renumber, shift_after
from shadow.ingest.text import strip_punct, to_simplified
from shadow.schemas import SegmentOut
from shadow.store.db import get_session
from shadow.store.models import Attempt, Lesson, Segment, SyllableScore

router = APIRouter()
MEDIA = {"wav": "audio/wav", "opus": "audio/ogg", "mp3": "audio/mpeg"}
SPLIT_MARGIN_S = 0.3     # each half of a resplit upload segment is re-aligned this far past the split point


def _get(db: Session, segment_id: int) -> Segment:
    seg = db.get(Segment, segment_id)
    if seg is None:
        raise HTTPException(404, "segment not found")
    return seg


def _fresh_out(db: Session, segment_id: int) -> SegmentOut:
    db.expire_all()                     # reenrich/renumber wrote through their own sessions
    return _segment_out(db, _get(db, segment_id))


@router.get("/segments/{segment_id}/audio")
def segment_audio(segment_id: int, request: Request, fmt: str = "opus", db: Session = Depends(get_session)):
    if fmt not in MEDIA:
        raise HTTPException(400, "fmt must be opus|wav|mp3")
    seg = _get(db, segment_id)
    if not seg.clip_wav_path or not seg.clip_opus_path:
        raise HTTPException(404, "segment has no clip")
    files = request.app.state.files
    path = {"wav": Path(seg.clip_wav_path), "opus": Path(seg.clip_opus_path),
            "mp3": files.clip_mp3(seg.lesson_id, seg.idx)}[fmt]
    if fmt == "mp3" and not path.exists() and Path(seg.clip_wav_path).exists():
        audio.encode_mp3(Path(seg.clip_wav_path), path)
    if not path.exists():
        raise HTTPException(404, "clip file missing")
    return FileResponse(path, media_type=MEDIA[fmt])


class SegmentPatch(BaseModel):
    difficulty_flag: bool | None = None
    text: str | None = None


@router.patch("/segments/{segment_id}", response_model=SegmentOut)
def patch_segment(segment_id: int, body: SegmentPatch, request: Request, db: Session = Depends(get_session)):
    """A text change re-runs align + enrich for the segment; text equal to the current one (after
    simplification) changes nothing."""
    seg = _get(db, segment_id)
    text = to_simplified(body.text).strip() if body.text is not None else None
    if text is not None and not strip_punct(text):
        raise HTTPException(400, "text needs at least one speech character")
    text_changed = text is not None and text != seg.text
    if body.difficulty_flag is not None:
        seg.difficulty_flag = body.difficulty_flag
    if text_changed:
        seg.text = text
    db.add(seg); db.commit()
    if text_changed:
        reenrich_segment(request.app.state.deps, request.app.state.engine, segment_id)
    return _fresh_out(db, segment_id)


class ResplitIn(BaseModel):
    at_char_index: int


def _split_time(seg: Segment, speech_before: int) -> float:
    """Time between the `speech_before`-th and the next speech character: from the reference alignment
    (source.wav time) when it covers the text, else proportional to the character count."""
    al = seg.ref_alignment_json or []
    n = len(strip_punct(seg.text))
    if len(al) == n:
        return (al[speech_before - 1]["end"] + al[speech_before]["start"]) / 2
    return seg.start_s + (seg.end_s - seg.start_s) * speech_before / n


@router.post("/segments/{segment_id}/resplit", response_model=list[SegmentOut])
def resplit(segment_id: int, body: ResplitIn, request: Request, db: Session = Depends(get_session)):
    """Split the text before `at_char_index` into two segments, the later ones moving up one idx."""
    seg = _get(db, segment_id)
    k = body.at_char_index
    left, right = seg.text[:k], seg.text[k:]
    if not 0 < k < len(seg.text) or not strip_punct(left) or not strip_punct(right):
        raise HTTPException(400, "at_char_index must leave speech characters on both sides")
    if seg.end_s - seg.start_s < 2 * MIN_CLIP_S:
        raise HTTPException(400, "segment is too short to split")
    split_t = round(min(max(_split_time(seg, len(strip_punct(left))), seg.start_s + MIN_CLIP_S),
                        seg.end_s - MIN_CLIP_S), 3)
    deps, engine = request.app.state.deps, request.app.state.engine
    fixed = db.get(Lesson, seg.lesson_id).source_type == "anki"
    old_start, old_end, lesson_id, idx = seg.start_s, seg.end_s, seg.lesson_id, seg.idx

    shift_after(deps, db, lesson_id, idx, +1)           # make room at idx + 1, clips included
    # the halves no longer correspond to a transcript char range
    seg.text, seg.end_s, seg.char_from, seg.char_to = left, split_t, None, None
    new = Segment(lesson_id=lesson_id, idx=idx + 1, start_s=split_t, end_s=old_end, text=right,
                  difficulty_flag=seg.difficulty_flag)
    db.add(seg); db.add(new); db.commit(); db.refresh(new)
    left_id, right_id = seg.id, new.id

    # Anki clips are the note's audio: each half is aligned inside exactly its share of it
    lw = None if fixed else (old_start, split_t + SPLIT_MARGIN_S)
    rw = None if fixed else (max(0.0, split_t - SPLIT_MARGIN_S), old_end)
    reenrich_segment(deps, engine, left_id, window=lw)
    reenrich_segment(deps, engine, right_id, window=rw)
    renumber(deps, engine, lesson_id)
    return [_fresh_out(db, left_id), _fresh_out(db, right_id)]


@router.post("/segments/{segment_id}/merge-next", response_model=SegmentOut)
def merge_next(segment_id: int, request: Request, db: Session = Depends(get_session)):
    """Append the next segment to this one; its attempts move here and the later segments move down one idx."""
    seg = _get(db, segment_id)
    nxt = db.exec(select(Segment).where(Segment.lesson_id == seg.lesson_id, Segment.idx == seg.idx + 1)).first()
    if nxt is None:
        raise HTTPException(409, "no next segment")
    deps, engine = request.app.state.deps, request.app.state.engine
    lesson_id = seg.lesson_id

    seg.text, seg.end_s = seg.text + nxt.text, nxt.end_s
    if seg.char_from is not None and nxt.char_to is not None:
        seg.char_to = nxt.char_to
    else:
        seg.char_from = seg.char_to = None
    seg.difficulty_flag = seg.difficulty_flag or nxt.difficulty_flag
    for row in (*db.exec(select(Attempt).where(Attempt.segment_id == nxt.id)).all(),
                *db.exec(select(SyllableScore).where(SyllableScore.segment_id == nxt.id)).all()):
        row.segment_id = seg.id
        db.add(row)
    if nxt.anki_note_id is not None and nxt.anki_note_id != seg.anki_note_id:
        lesson = db.get(Lesson, lesson_id)     # keep a re-import from bringing the merged note back
        meta = lesson.meta_json or {}
        lesson.meta_json = {**meta, "skipped_notes": {**meta.get("skipped_notes", {}),
                                                      str(nxt.anki_note_id): "merged into the previous segment"}}
        db.add(lesson)
    for p in (nxt.clip_wav_path, nxt.clip_opus_path, str(deps.files.clip_mp3(lesson_id, nxt.idx))):
        if p:
            Path(p).unlink(missing_ok=True)
    gone_idx = nxt.idx
    db.delete(nxt); db.add(seg); db.flush()
    shift_after(deps, db, lesson_id, gone_idx, -1)
    db.commit()
    sid = seg.id
    reenrich_segment(deps, engine, sid)
    renumber(deps, engine, lesson_id)
    return _fresh_out(db, sid)
