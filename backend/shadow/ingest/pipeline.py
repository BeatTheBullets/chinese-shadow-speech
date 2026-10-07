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
from shadow.ingest.subalign import MIN_SUBTITLE_MATCH, align_text_to_asr
from shadow.ingest.text import is_punct, parse_subtitles, strip_punct
from shadow.ingest.transcript import Transcript
from shadow.jobs import Progress
from shadow.store.models import Lesson, Segment

log = logging.getLogger(__name__)

WINDOW_MARGIN_S = 1.0   # alignment window around a sentence's coarse transcript times (spec §3.4)
MIN_CLIP_S = 0.05       # anything shorter is a degenerate clip (ffmpeg cannot cut zero length)


class NoSpeechError(RuntimeError):
    pass


def _set_status(engine: Engine, lesson_id: int, status: str, error: str | None = None, **fields) -> None:
    """No-op when the lesson has been deleted (e.g. while its ingest job was running)."""
    with Session(engine) as db:
        lesson = db.get(Lesson, lesson_id)
        if lesson is None:
            return
        lesson.status, lesson.error = status, error
        for k, v in fields.items():
            setattr(lesson, k, v)
        db.add(lesson); db.commit()


def _merge_meta(engine: Engine, lesson_id: int, **items) -> None:
    """No-op when the lesson has been deleted."""
    with Session(engine) as db:
        lesson = db.get(Lesson, lesson_id)
        if lesson is None:
            return
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
                   idx_offset: int = 0, fixed_spans: list[tuple[float, float]] | None = None,
                   translations: list[str | None] | None = None) -> None:
    """Align, enrich and clip `sentences`; writes Segment rows numbered from `idx_offset`.

    Default (upload): each sentence is aligned inside its coarse transcript times ±1 s and its clip is the
    padded alignment clamped to its neighbours (`clip_bounds`); a sentence that cannot be aligned falls back
    to its coarse times. With `fixed_spans` (Anki, one per sentence) each sentence is aligned inside exactly
    its span (clamped to the audio), the span is the clip, and the segment has no transcript char range; `tr`
    is then unused and may be None. `translations` (aligned with `sentences`) holds ready-made translations; only
    sentences whose entry is None are sent to the LLM."""
    if fixed_spans is None and tr is None:
        raise ValueError("a transcript is required unless fixed_spans are given")
    if fixed_spans is not None and len(fixed_spans) != len(sentences):
        raise ValueError(f"{len(fixed_spans)} fixed spans for {len(sentences)} sentences")
    if translations is not None and len(translations) != len(sentences):
        raise ValueError(f"{len(translations)} translations for {len(sentences)} sentences")
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
    translations = list(translations) if translations is not None else [None] * n
    todo = [i for i, t in enumerate(translations) if not t]
    if todo and deps.llm is not None and deps.settings.llm.translate:
        try:
            got = translate_all(deps.llm, [texts[i] for i in todo])
            if len(got) != len(todo):
                raise ValueError(f"{len(got)} translations for {len(todo)} sentences")
            for i, t in zip(todo, got):
                translations[i] = t
        except Exception as e:  # noqa: BLE001  translation is optional (spec §3.5)
            log.warning("translation failed; storing segments without translations", exc_info=True)
            _merge_meta(engine, lesson_id, translation_error=str(e) or type(e).__name__)

    with Session(engine) as db:
        if db.get(Lesson, lesson_id) is None:     # deleted while this job ran: write no orphan rows
            log.warning("lesson %d was deleted during ingest; discarding its segments", lesson_id)
            return
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


def _subtitle_lines(subtitle: tuple[str, str]) -> tuple[list[str], str | None]:
    """(text per cue or per plain-text line, None) for usable subtitles, else ([], reason they are ignored).
    Their times are never used: timing comes from the ASR."""
    name, content = subtitle
    try:
        cues = parse_subtitles(content, name)
    except ValueError as e:
        return [], f"could not parse {name}: {e}"
    lines = [c.text for c in sorted(cues, key=lambda c: c.start)]
    if not any(strip_punct(t) for t in lines):
        return [], f"{name} has no text"
    return lines, None


def _subtitle_transcript(subtitle: tuple[str, str], asr: Transcript) -> tuple[Transcript | None, dict]:
    """The subtitle text timed from the `asr` transcript (spec §3.2), or None when the subtitles are unusable or
    do not match the audio; plus the lesson meta to record (`subtitle_match` or `subtitle_ignored`)."""
    lines, ignored = _subtitle_lines(subtitle)
    if not ignored:
        tr, ratio = align_text_to_asr(lines, asr)
        if ratio >= MIN_SUBTITLE_MATCH:
            return tr, {"subtitle_match": round(ratio, 2)}
        ignored = f"subtitles don't match the audio ({int(ratio * 100)} % of characters matched)"
    log.warning("ignoring subtitles (%s); using the ASR transcript instead", ignored)
    return None, {"subtitle_ignored": ignored}


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
        tr = deps.asr.transcribe(source_wav)        # always: even with subtitles, timing comes from the ASR
        if not _has_speech(tr):
            raise NoSpeechError("no speech found in the recording")
        from_subtitles = False
        if subtitle is not None:
            sub_tr, meta = _subtitle_transcript(subtitle, tr)
            _merge_meta(engine, lesson_id, **meta)
            if sub_tr is not None:
                tr, from_subtitles = sub_tr, True
        progress("transcribe", 1.0)

        progress("rectify", 0.0)
        # subtitle text is a human transcript: the LLM may only choose boundaries and punctuation
        sentences = rectify_transcript(tr, deps.llm, enabled=deps.settings.llm.rectify, locked=from_subtitles)
        progress("rectify", 1.0)

        build_segments(deps, engine, lesson_id, source_wav, tr, sentences, progress)
        _set_status(engine, lesson_id, "ready", duration_s=duration, transcript_json=tr.to_json())
        progress("done", 1.0)
    except Exception as e:  # noqa: BLE001
        _set_status(engine, lesson_id, "error", error=str(e) or type(e).__name__)
        raise
