import logging
import pytest
from sqlmodel import Session, select
from shadow.ingest.align import FakeAligner, Span
from shadow.ingest.pipeline import NoSpeechError, build_segments, clip_bounds, ingest_upload
from shadow.ingest.rectify import RectSentenceOut
from shadow.ingest.text import Cue
from shadow.ingest.transcript import Transcript, transcript_from_cues
from shadow.store.models import Lesson, Segment
from shadow.deps import fake_deps
from shadow.config import Settings
from shadow.store.db import make_engine, init_db
from tests.conftest import LESSON_TEXT
from tests.helpers import make_tone_wav


def _lesson(engine):
    with Session(engine) as db:
        l = Lesson(title="t", speaker="s", source_type="upload", source_ref="t.wav")
        db.add(l); db.commit(); db.refresh(l)
        return l.id


def _setup(data_dir, transcript):
    settings = Settings(data_dir=data_dir)
    deps = fake_deps(settings, transcript)
    engine = make_engine(data_dir); init_db(engine)
    return deps, engine, _lesson(engine)


def _segments(engine, lid):
    with Session(engine) as db:
        return db.exec(select(Segment).where(Segment.lesson_id == lid).order_by(Segment.idx)).all()


def _get_lesson(engine, lid):
    with Session(engine) as db:
        return db.get(Lesson, lid)


def test_ingest_upload_creates_segments(data_dir, fake_transcript, tmp_path):
    deps, engine, lid = _setup(data_dir, fake_transcript)
    stages = []
    ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 8.0), None, lambda s, f: stages.append(s))
    lesson, segs = _get_lesson(engine, lid), _segments(engine, lid)
    assert lesson.status == "ready" and abs(lesson.duration_s - 8.0) < 0.05
    assert [s.text for s in segs] == ["我今天想跟你们聊一聊学中文的方法。", "其实方法有很多。", "但是最重要的是坚持。"]
    assert segs[0].start_s == 0.0 and segs[0].end_s <= segs[1].start_s
    assert segs[0].words_json[1]["word"] == "今天"
    assert len(segs[0].ref_alignment_json) == 16
    assert segs[0].translation.startswith("en:")
    assert deps.files.clip_wav(lid, 0).exists() and deps.files.clip_opus(lid, 2).exists()
    assert lesson.transcript_json["chars"][0]["c"] == "我"
    assert list(dict.fromkeys(stages))[:2] == ["normalise", "transcribe"] and stages[-1] == "done"
    assert deps.llm.rectify_locked == [False]           # ASR text is repaired, not locked


def test_ingest_upload_segments_cover_transcript_in_order(data_dir, fake_transcript, tmp_path):
    deps, engine, lid = _setup(data_dir, fake_transcript)
    ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 8.0), None, lambda s, f: None)
    segs = _segments(engine, lid)
    assert [(s.char_from, s.char_to) for s in segs] == [(0, 16), (17, 24), (25, 34)]
    for s in segs:
        assert sum(len(w["syllables"]) for w in s.words_json) == len(s.ref_alignment_json)
    for a, b in zip(segs, segs[1:]):
        assert a.start_s < a.end_s <= b.start_s


def test_clip_bounds_pads_and_clamps_to_neighbours():
    bounds = clip_bounds([(0.1, 2.9), (3.0, 4.9), (5.1, 7.95)], pad=0.12, total=8.0)
    assert bounds == [(0.0, 3.0), (3.0, 5.02), (5.02, 8.0)]


def test_clip_bounds_uses_own_envelope_when_neighbours_overlap():
    # sentence 1 was aligned before sentence 0: clamping would leave nothing to cut for either
    bounds = clip_bounds([(1.0, 3.0), (0.5, 0.9), (4.0, 5.0)], pad=0.12, total=8.0)
    assert bounds == [(0.88, 3.12), (0.38, 1.02), (3.88, 5.12)]


def test_clip_bounds_skips_sentence_outside_the_audio():
    bounds = clip_bounds([(0.5, 1.5), (9.0, 10.0)], pad=0.12, total=2.0)
    assert bounds == [(0.38, 1.62), None]


class _NoAligner:
    """Aligns nothing, so every sentence falls back to its coarse transcript times."""

    def align(self, wav, sr, text):
        return []


def _srt(cues):
    return "".join(f"{i + 1}\n00:00:{a:06.3f} --> 00:00:{b:06.3f}\n{t}\n\n".replace(".", ",")
                   for i, (a, b, t) in enumerate(cues))


def test_ingest_upload_takes_text_from_subtitles_and_timing_from_asr(data_dir, tmp_path):
    # the ASR mishears 学 as 雪; the subtitle cues are 5 s late (another release with a longer intro)
    asr = transcript_from_cues([Cue(a, b, t.replace("学", "雪")) for a, b, t in LESSON_TEXT])
    deps, engine, lid = _setup(data_dir, asr)
    deps.aligner = _NoAligner()
    srt = _srt([(a + 5, b + 5, t) for a, b, t in LESSON_TEXT])
    ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 8.0), ("a.srt", srt), lambda s, f: None)
    lesson, segs = _get_lesson(engine, lid), _segments(engine, lid)
    assert lesson.status == "ready"
    assert [s.text for s in segs] == [t for _, _, t in LESSON_TEXT]
    # coarse times are the ASR's (0-3, 3-5, 5-7.5 s), padded and clamped; the cues' 5-12.5 s are not used
    assert [(s.start_s, s.end_s) for s in segs] == [(0.0, 3.0), (3.0, 5.0), (5.0, 7.62)]
    assert lesson.transcript_json["chars"][10]["c"] == "学"            # the subtitle's text, not the ASR's 雪
    assert lesson.meta_json["subtitle_match"] == 0.97                   # 31 of 32 speech chars
    assert "subtitle_ignored" not in lesson.meta_json
    assert deps.llm.rectify_locked == [True]


def test_ingest_upload_uses_a_plain_text_transcript(data_dir, fake_transcript, tmp_path):
    deps, engine, lid = _setup(data_dir, fake_transcript)
    lines = ["我今天想跟你们聊一聊", "学中文的方法其实方法有很多", "但是最重要的是坚持"]
    ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 8.0), ("a.txt", "\n".join(lines) + "\n"),
                  lambda s, f: None)
    lesson, segs = _get_lesson(engine, lid), _segments(engine, lid)
    assert lesson.status == "ready"
    assert [s.text for s in segs] == lines
    assert [(s.char_from, s.char_to) for s in segs] == [(0, 9), (10, 22), (23, 31)]
    assert lesson.meta_json == {"subtitle_match": 1.0}
    chars = lesson.transcript_json["chars"]
    assert chars[10]["c"] == "学" and chars[10]["start"] == fake_transcript.chars[10].start


def test_ingest_upload_ignores_subtitles_for_other_speech_and_uses_asr(data_dir, fake_transcript, tmp_path, caplog):
    deps, engine, lid = _setup(data_dir, fake_transcript)
    srt = _srt([(0.0, 2.0, "大家好。"), (2.0, 4.0, "欢迎回来。")])
    with caplog.at_level(logging.WARNING):
        ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 8.0), ("a.srt", srt), lambda s, f: None)
    lesson = _get_lesson(engine, lid)
    assert lesson.status == "ready"
    assert [s.text for s in _segments(engine, lid)] == [t for _, _, t in LESSON_TEXT]
    assert lesson.meta_json == {"subtitle_ignored": "subtitles don't match the audio (0 % of characters matched)"}
    assert "match" in caplog.text
    assert deps.llm.rectify_locked == [False]


def test_ingest_upload_with_rolling_auto_captions_has_no_repeated_sentences(data_dir, fake_transcript, tmp_path):
    deps, engine, lid = _setup(data_dir, fake_transcript)
    lines = ["我今天想跟你们聊一聊", "学中文的方法", "其实方法有很多", "但是最重要的是坚持"]
    vtt, t, prev = "WEBVTT\nKind: captions\nLanguage: zh\n\n", 0.0, None
    for line in lines:                       # yt-dlp style: A, (A), A\nB, (B), B\nC ...
        vtt += f"00:00:{t:06.3f} --> 00:00:{t + 1.5:06.3f} align:start position:0%\n"
        vtt += f"{prev}\n{line}\n\n" if prev else f" \n{line}\n\n"
        vtt += f"00:00:{t + 1.5:06.3f} --> 00:00:{t + 1.51:06.3f} align:start position:0%\n{line}\n \n\n"
        t, prev = t + 1.51, line
    ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 8.0), ("auto.zh.vtt", vtt), lambda s, f: None)
    lesson = _get_lesson(engine, lid)
    assert [s.text for s in _segments(engine, lid)] == lines
    assert lesson.meta_json == {"subtitle_match": 1.0}


def test_ingest_upload_ignores_malformed_subtitles_and_uses_asr(data_dir, fake_transcript, tmp_path):
    deps, engine, lid = _setup(data_dir, fake_transcript)
    srt = "1\n00:00:xx --> 00:00:02,000\n大家好。\n"
    ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 8.0), ("a.srt", srt), lambda s, f: None)
    lesson = _get_lesson(engine, lid)
    assert lesson.status == "ready" and len(_segments(engine, lid)) == 3
    assert "timestamp" in lesson.meta_json["subtitle_ignored"]


def test_ingest_upload_ignores_empty_subtitles_and_uses_asr(data_dir, fake_transcript, tmp_path):
    deps, engine, lid = _setup(data_dir, fake_transcript)
    ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 8.0), ("a.srt", "\n"), lambda s, f: None)
    lesson = _get_lesson(engine, lid)
    assert lesson.status == "ready" and len(_segments(engine, lid)) == 3
    assert lesson.meta_json["subtitle_ignored"] == "a.srt has no text"


def test_ingest_upload_with_subtitles_and_no_speech_sets_error(data_dir, tmp_path):
    deps, engine, lid = _setup(data_dir, Transcript())
    srt = _srt([(0.0, 2.0, "大家好。")])
    with pytest.raises(NoSpeechError):
        ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 2.0), ("a.srt", srt), lambda s, f: None)
    lesson = _get_lesson(engine, lid)
    assert lesson.status == "error" and "no speech" in lesson.error.lower()


def test_ingest_upload_rectifies_subtitle_text_locked_and_simplifies_llm_output(data_dir, tmp_path):
    from shadow.ingest.llm import RectifyOutput, RectSentence
    deps, engine, lid = _setup(data_dir, transcript_from_cues([Cue(0.0, 2.0, "欢迎回来")]))
    calls = []

    def rectify(chunk, ctx):
        calls.append("".join(chunk))
        return RectifyOutput(sentences=[RectSentence(**{"from": 0, "to": len(chunk) - 1, "text": "歡迎回來。"})])
    deps.llm._r = rectify
    srt = "1\n00:00:00,000 --> 00:00:02,000\n欢迎回来\n"
    ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 2.0), ("a.srt", srt), lambda s, f: None)
    assert calls == ["欢迎回来"] and deps.llm.rectify_locked == [True]
    assert [s.text for s in _segments(engine, lid)] == ["欢迎回来。"]


def test_ingest_upload_with_no_speech_sets_error(data_dir, tmp_path):
    deps, engine, lid = _setup(data_dir, Transcript())
    with pytest.raises(NoSpeechError):
        ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 2.0), None, lambda s, f: None)
    lesson = _get_lesson(engine, lid)
    assert lesson.status == "error" and "no speech" in lesson.error.lower()


def test_ingest_upload_with_punctuation_only_asr_sets_no_speech_error(data_dir, tmp_path):
    deps, engine, lid = _setup(data_dir, transcript_from_cues([Cue(0.0, 1.0, "。。")]))
    with pytest.raises(NoSpeechError):
        ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 2.0), None, lambda s, f: None)
    assert "no speech" in _get_lesson(engine, lid).error.lower()


def test_translation_failure_keeps_lesson_and_records_error(data_dir, fake_transcript, tmp_path, caplog):
    deps, engine, lid = _setup(data_dir, fake_transcript)

    def broken(xs):
        raise RuntimeError("api down")
    deps.llm._t = broken
    with caplog.at_level(logging.WARNING):
        ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 8.0), None, lambda s, f: None)
    lesson, segs = _get_lesson(engine, lid), _segments(engine, lid)
    assert lesson.status == "ready" and len(segs) == 3
    assert all(s.translation is None for s in segs)
    assert "api down" in lesson.meta_json["translation_error"]
    assert "translation" in caplog.text.lower()


class _FlakyAligner:
    """Raises for the sentence containing `bad`, returns nothing for one containing `empty`."""

    def __init__(self, bad: str, empty: str):
        self.bad, self.empty = bad, empty

    def align(self, wav, sr, text):
        if self.bad in text:
            raise ValueError("tokenizer dropped a word")
        if self.empty in text:
            return []
        return FakeAligner().align(wav, sr, text)


def test_failed_or_empty_alignment_falls_back_to_coarse_times(data_dir, fake_transcript, tmp_path, caplog):
    deps, engine, lid = _setup(data_dir, fake_transcript)
    deps.aligner = _FlakyAligner(bad="其实", empty="坚持")
    with caplog.at_level(logging.WARNING):
        ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 8.0), None, lambda s, f: None)
    segs = _segments(engine, lid)
    assert _get_lesson(engine, lid).status == "ready" and len(segs) == 3
    # sentences 1 and 2 use their coarse transcript times (3.0..5.0, 5.0..7.5), padded and clamped
    assert [(s.start_s, s.end_s) for s in segs[1:]] == [(3.0, 5.0), (5.0, 7.62)]
    assert segs[1].ref_alignment_json == [] and segs[2].ref_alignment_json == []
    assert caplog.text.count("alignment") >= 2


def test_build_segments_with_fixed_spans(data_dir, tmp_path):
    from shadow.ingest import audio
    deps, engine, lid = _setup(data_dir, Transcript())
    texts = ["你好。", "谢谢你。"]
    tr = transcript_from_cues([Cue(0.0, 1.5, texts[0]), Cue(2.0, 3.5, texts[1])])
    sentences = [RectSentenceOut(0, 2, texts[0]), RectSentenceOut(3, 6, texts[1])]
    src = deps.files.source_wav(lid)
    audio.normalise(make_tone_wav(tmp_path / "t.wav", 4.0), src)
    build_segments(deps, engine, lid, src, tr, sentences, lambda s, f: None,
                   anki_note_ids=[11, 22], idx_offset=5, fixed_spans=[(0.0, 1.5), (2.0, 3.5)])
    segs = _segments(engine, lid)
    assert [s.idx for s in segs] == [5, 6] and [s.anki_note_id for s in segs] == [11, 22]
    assert [(s.start_s, s.end_s) for s in segs] == [(0.0, 1.5), (2.0, 3.5)]
    assert all(s.char_from is None and s.char_to is None for s in segs)
    second = segs[1].ref_alignment_json
    assert len(second) == 3 and second[0]["start"] == pytest.approx(2.0) and second[-1]["end"] == pytest.approx(3.5)
    assert deps.files.clip_wav(lid, 6).exists()


def test_spans_to_json_rounds():
    from shadow.ingest.align import spans_to_json
    assert spans_to_json([Span("你", 0.12345, 0.5, 0.98765)]) == [{"ch": "你", "start": 0.123, "end": 0.5, "conf": 0.988}]


def test_build_segments_fixed_spans_need_no_transcript(data_dir, tmp_path):
    from shadow.ingest import audio
    deps, engine, lid = _setup(data_dir, Transcript())
    src = deps.files.source_wav(lid)
    audio.normalise(make_tone_wav(tmp_path / "t.wav", 3.0), src)
    build_segments(deps, engine, lid, src, None, [RectSentenceOut(0, 0, "你好。")], lambda s, f: None,
                   fixed_spans=[(0.0, 1.5)])
    assert [(s.start_s, s.end_s) for s in _segments(engine, lid)] == [(0.0, 1.5)]


def test_build_segments_needs_transcript_or_fixed_spans(data_dir, tmp_path):
    from shadow.ingest import audio
    deps, engine, lid = _setup(data_dir, Transcript())
    src = deps.files.source_wav(lid)
    audio.normalise(make_tone_wav(tmp_path / "t.wav", 1.0), src)
    with pytest.raises(ValueError):
        build_segments(deps, engine, lid, src, None, [RectSentenceOut(0, 0, "你好。")], lambda s, f: None)


def test_build_segments_clamps_fixed_spans_to_audio(data_dir, tmp_path, caplog):
    from shadow.ingest import audio
    deps, engine, lid = _setup(data_dir, Transcript())
    src = deps.files.source_wav(lid)
    audio.normalise(make_tone_wav(tmp_path / "t.wav", 3.0), src)
    sentences = [RectSentenceOut(0, 0, "你好。"), RectSentenceOut(0, 0, "谢谢你。"), RectSentenceOut(0, 0, "再见。")]
    with caplog.at_level(logging.WARNING):
        build_segments(deps, engine, lid, src, None, sentences, lambda s, f: None,
                       anki_note_ids=[1, 2, 3], fixed_spans=[(0.0, 1.5), (2.0, 9.0), (5.0, 6.5)])
    segs = _segments(engine, lid)
    # the second is clamped to the audio end, the third lies entirely past it and is skipped
    assert [(s.anki_note_id, s.start_s, s.end_s) for s in segs] == [(1, 0.0, 1.5), (2, 2.0, pytest.approx(3.0, abs=0.01))]
    assert "degenerate" in caplog.text


def test_build_segments_translates_only_sentences_without_one(data_dir, tmp_path):
    from shadow.ingest import audio
    deps, engine, lid = _setup(data_dir, Transcript())
    deps.settings.llm.translate = True
    asked = []
    deps.llm._t = lambda xs: (asked.append(list(xs)), [f"en:{x}" for x in xs])[1]
    src = deps.files.source_wav(lid)
    audio.normalise(make_tone_wav(tmp_path / "t.wav", 4.0), src)
    sentences = [RectSentenceOut(0, 0, "你好。"), RectSentenceOut(0, 0, "谢谢你。")]
    build_segments(deps, engine, lid, src, None, sentences, lambda s, f: None,
                   fixed_spans=[(0.0, 1.5), (2.0, 3.5)], translations=["Hello", None])
    assert asked == [["谢谢你。"]]
    assert [s.translation for s in _segments(engine, lid)] == ["Hello", "en:谢谢你。"]
