from sqlmodel import Session as DbSession, select
from shadow.store.db import make_engine, init_db
from shadow.store.models import Lesson, Segment, Attempt, PracticeSession, SyllableScore
from shadow.store.files import FileLayout


def test_roundtrip_lesson_segment_attempt(data_dir):
    engine = make_engine(data_dir)
    init_db(engine)
    with DbSession(engine) as db:
        lesson = Lesson(title="t", speaker="s", source_type="upload", source_ref="x.mp4", status="ready")
        db.add(lesson); db.commit(); db.refresh(lesson)
        seg = Segment(lesson_id=lesson.id, idx=0, start_s=0.0, end_s=1.2, text="你好。",
                      words_json=[{"word": "你好", "pinyin": "nǐhǎo", "tones": [3, 3], "char_from": 0, "char_to": 1}],
                      ref_alignment_json=[{"ch": "你", "start": 0.1, "end": 0.5, "conf": 0.9}])
        db.add(seg); db.commit(); db.refresh(seg)
        ps = PracticeSession(lesson_id=lesson.id, mode="echo")
        db.add(ps); db.commit(); db.refresh(ps)
        att = Attempt(segment_id=seg.id, session_id=ps.id, mode="echo", audio_path="a.wav", duration_s=1.0)
        db.add(att); db.commit(); db.refresh(att)
        db.add(SyllableScore(attempt_id=att.id, segment_id=seg.id, idx=0, ch="你", pinyin_toneless="ni",
                             tone=3, prev_tone=None, tone_score=0.8, seg_score=None, status="ok"))
        db.commit()
        got = db.exec(select(Segment).where(Segment.lesson_id == lesson.id)).one()
        assert got.words_json[0]["word"] == "你好"
        assert got.ref_alignment_json[0]["ch"] == "你"
        assert db.exec(select(SyllableScore)).one().tone == 3


def test_file_layout(data_dir):
    fl = FileLayout(data_dir)
    assert fl.clip_wav(7, 3) == data_dir / "lessons" / "7" / "clips" / "3.wav"
    assert fl.attempt_wav(12) == data_dir / "attempts" / "12.wav"
    fl.lesson_dir(7).mkdir(parents=True)
    assert fl.source_wav(7).parent.exists()
