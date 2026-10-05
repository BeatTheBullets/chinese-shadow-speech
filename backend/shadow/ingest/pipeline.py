from __future__ import annotations
import logging
import subprocess
from pathlib import Path
import numpy as np
from sqlalchemy import Engine
from sqlmodel import Session
from shadow.deps import Deps
from shadow.ingest import audio
from shadow.ingest.align import Span, align_in_window, sentence_bounds, spans_to_json
from shadow.ingest.enrich import make_clips, translate_all, words_for
from shadow.ingest.rectify import RectSentenceOut, rectify_transcript
from shadow.ingest.text import is_punct, parse_subtitles
from shadow.ingest.transcript import Transcript, transcript_from_cues
from shadow.jobs import Progress
from shadow.store.models import Lesson, Segment

log = logging.getLogger(__name__)

WINDOW_MARGIN_S = 1.0   # alignment window around a sentence's coarse transcript times (spec §3.4)
MIN_CLIP_S = 0.05       # anything shorter is a degenerate clip (ffmpeg cannot cut zero length)


class NoSpeechError(RuntimeError):
    pass


def _set_status(engine: Engine, lesson_id: int, status: str, error: str | None = None, **fields) -> None:
    with Session(engine) as db:
        lesson = db.get(Lesson, lesson_id)
        lesson.status, lesson.error = status, error
        for k, v in fields.items():
            setattr(lesson, k, v)
        db.add(lesson); db.commit()


def _merge_meta(engine: Engine, lesson_id: int, **items) -> None:
    with Session(engine) as db:
        lesson = db.get(Lesson, lesson_id)
        lesson.meta_json = {**(lesson.meta_json or {}), **items}
        db.add(lesson); db.commit()


def _has_speech(tr: Transcript) -> bool:
    return any(not is_punct(c.c) for c in tr.chars)


def _align(deps: Deps, wav: np.ndarray, sr: int, i: int, text: str, win_start: float, win_end: float) -> list[Span]:
    """Spans for one sentence, or [] (with a warning) when the aligner fails or finds nothing."""
    try:
        spans = align_in_window(deps.aligner, wav, sr, text, win_start, win_end)
    except Exception:  # noqa: BLE001
        log.warning("alignment failed for sentence %d %r; using sentence-level timing", i, text, exc_info=True)
        return []
    if not spans:
        log.warning("alignment returned no spans for sentence %d %r; using sentence-level timing", i, text)
    return spans


def clip_bounds(envelopes: list[tuple[float, float]], pad: float, total: float) -> list[tuple[float, float] | None]:
    """Clip (start, end) per sentence from its speech envelope (first span start, last span end): padded by `pad`,
    clamped to the previous clip's end, the next sentence's speech start and [0, total]. If clamping leaves a
    degenerate clip (neighbours aligned on top of each other) the sentence's own padded envelope is used;
    None when even that lies outside the audio."""
    out: list[tuple[float, float] | None] = []
    prev_end = 0.0
    for i, (a, b) in enumerate(envelopes):
        next_start = envelopes[i + 1][0] if i + 1 < len(envelopes) else total
        start, end = sentence_bounds([Span("", a, b, 0.0)], pad, prev_end, next_start, total)
        if end - start < MIN_CLIP_S:
            start, end = round(max(a - pad, 0.0), 3), round(min(b + pad, total), 3)
            if end - start < MIN_CLIP_S:
                log.warning("sentence %d (%.2f-%.2f s) is outside the audio (%.2f s); skipping it", i, a, b, total)
                out.append(None)
                continue
            log.warning("sentence %d overlaps its neighbours; using its own padded times %.2f-%.2f s", i, start, end)
        out.append((start, end))
        prev_end = max(prev_end, end)
    return out


def build_segments(deps: Deps, engine: Engine, lesson_id: int, source_wav: Path, tr: Transcript | None,
                   sentences: list[RectSentenceOut], progress: Progress, anki_note_ids: list[int] | None = None,
                   idx_offset: int = 0, fixed_spans: list[tuple[float, float]] | None = None) -> None:
    """Align, enrich and clip `sentences`; writes Segment rows numbered from `idx_offset`.

    Default (upload): each sentence is aligned inside its coarse transcript times ±1 s and its clip is the
    padded alignment clamped to its neighbours (`clip_bounds`); a sentence that cannot be aligned falls back
    to its coarse times. With `fixed_spans` (Anki, one per sentence) each sentence is aligned inside exactly
    its span (clamped to the audio), the span is the clip, and the segment has no transcript char range; `tr`
    is then unused and may be None."""
    if fixed_spans is None and tr is None:
        raise ValueError("a transcript is required unless fixed_spans are given")
    if fixed_spans is not None and len(fixed_spans) != len(sentences):
        raise ValueError(f"{len(fixed_spans)} fixed spans for {len(sentences)} sentences")
    wav, sr = audio.read_wav(source_wav)
    total = len(wav) / sr
    if fixed_spans is not None:
        fixed_spans = [(min(max(a, 0.0), total), min(max(b, 0.0), total)) for a, b in fixed_spans]
    pad = deps.settings.segmentation.pad_ms / 1000
    texts = [s.text for s in sentences]
    n = len(sentences)

    progress("align", 0.0)
    aligned: list[list[Span]] = []
    for i, s in enumerate(sentences):
        if fixed_spans is not None:
            win = fixed_spans[i]
            if win[1] - win[0] < MIN_CLIP_S:        # degenerate or past the audio: skipped below
                aligned.append([])
                progress("align", (i + 1) / n)
                continue
        else:
            win = (max(0.0, tr.chars[s.char_from].start - WINDOW_MARGIN_S),
                   min(total, tr.chars[s.char_to].end + WINDOW_MARGIN_S))
        aligned.append(_align(deps, wav, sr, i, texts[i], *win))
        progress("align", (i + 1) / n)

    if fixed_spans is not None:
        bounds: list[tuple[float, float] | None] = [
            (round(a, 3), round(b, 3)) if b - a >= MIN_CLIP_S else None for a, b in fixed_spans]
        for i in (i for i, b in enumerate(bounds) if b is None):
            log.warning("sentence %d has a degenerate span %s; skipping it", i, fixed_spans[i])
    else:
        envelopes = [(sp[0].start, sp[-1].end) if sp else (tr.chars[s.char_from].start, tr.chars[s.char_to].end)
                     for sp, s in zip(aligned, sentences)]
        bounds = clip_bounds(envelopes, pad, total)
    if not any(bounds):
        raise NoSpeechError("none of the sentences could be placed within the audio")

    progress("enrich", 0.0)
    translations: list[str | None] = [None] * n
    if deps.llm is not None and deps.settings.llm.translate:
        try:
            got = translate_all(deps.llm, texts)
            if len(got) != n:
                raise ValueError(f"{len(got)} translations for {n} sentences")
            translations = list(got)
        except Exception as e:  # noqa: BLE001  translation is optional (spec §3.5)
            log.warning("translation failed; storing segments without translations", exc_info=True)
            _merge_meta(engine, lesson_id, translation_error=str(e) or type(e).__name__)

    with Session(engine) as db:
        idx = idx_offset
        for i, s in enumerate(sentences):
            if bounds[i] is not None:
                start, end = bounds[i]
                clip_wav, clip_opus = make_clips(deps.files, lesson_id, idx, source_wav, start, end)
                db.add(Segment(
                    lesson_id=lesson_id, idx=idx, start_s=start, end_s=end,
                    char_from=None if fixed_spans is not None else s.char_from,
                    char_to=None if fixed_spans is not None else s.char_to,
                    text=texts[i], translation=translations[i] or None, words_json=words_for(texts[i]),
                    ref_alignment_json=spans_to_json(aligned[i]),
                    anki_note_id=anki_note_ids[i] if anki_note_ids else None,
                    clip_wav_path=str(clip_wav), clip_opus_path=str(clip_opus),
                ))
                idx += 1
            progress("enrich", (i + 1) / n)
        db.commit()


def _subtitle_transcript(subtitle: tuple[str, str]) -> tuple[Transcript | None, str | None]:
    """(transcript, None) for usable subtitles, else (None, reason they are ignored)."""
    name, content = subtitle
    try:
        cues = parse_subtitles(content, name)
    except ValueError as e:
        return None, f"could not parse {name}: {e}"
    timed = [c for c in cues if c.start >= 0]
    if not timed:
        return None, f"{name} has no timed cues"
    tr = transcript_from_cues(timed)
    if not _has_speech(tr):
        return None, f"{name} has no text"
    return tr, None


def ingest_upload(deps: Deps, engine: Engine, lesson_id: int, media_path: Path,
                  subtitle: tuple[str, str] | None, progress: Progress) -> None:
    """Spec §3.1–3.5 for an uploaded file (+ optional (filename, content) subtitles). Sets the lesson's
    status to `ready`, or to `error` with a message and re-raises so the job is marked failed."""
    try:
        _set_status(engine, lesson_id, "processing")
        progress("normalise", 0.0)
        source_wav = deps.files.source_wav(lesson_id)
        try:
            audio.normalise(media_path, source_wav)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"could not read audio from {media_path.name}") from e
        duration = audio.duration_s(source_wav)
        progress("normalise", 1.0)

        progress("transcribe", 0.0)
        tr = None
        if subtitle is not None:
            tr, ignored = _subtitle_transcript(subtitle)
            if ignored:
                log.warning("ignoring subtitles (%s); transcribing with ASR instead", ignored)
                _merge_meta(engine, lesson_id, subtitle_ignored=ignored)
        if tr is None:
            tr = deps.asr.transcribe(source_wav)
        if not _has_speech(tr):
            raise NoSpeechError("no speech found in the recording")
        progress("transcribe", 1.0)

        progress("rectify", 0.0)
        sentences = rectify_transcript(tr, deps.llm, enabled=deps.settings.llm.rectify)
        progress("rectify", 1.0)

        build_segments(deps, engine, lesson_id, source_wav, tr, sentences, progress)
        _set_status(engine, lesson_id, "ready", duration_s=duration, transcript_json=tr.to_json())
        progress("done", 1.0)
    except Exception as e:  # noqa: BLE001
        _set_status(engine, lesson_id, "error", error=str(e) or type(e).__name__)
        raise
