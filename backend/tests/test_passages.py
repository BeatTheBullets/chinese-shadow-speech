from sqlmodel import Session, select
from shadow.ingest.passages import PassagePlan, default_title, passage_index, passage_views, plan_passages, rebuild_passages
from shadow.store.db import init_db, make_engine
from shadow.store.models import Lesson, Passage, Segment


def _uniform(n, length=10.0, gap=1.0):
    return [(k * (length + gap), k * (length + gap) + length) for k in range(n)]


def test_a_lesson_under_four_minutes_is_one_passage_even_with_chapters():
    chapters = [{"title": "一", "start_time": 0.0, "end_time": 100.0}, {"title": "二", "start_time": 100.0, "end_time": 220.0}]
    assert plan_passages(_uniform(20), chapters) == [PassagePlan(0.0, 219.0)]          # 0 … 219 s


def test_greedy_cuts_at_the_largest_pause_in_the_window_then_nearest_150_s():
    # 10 s segments with 1 s pauses, except a 3 s pause before the segment at 145 s
    segs = [(11.0 * k, 11.0 * k + 10) for k in range(13)] + [(11.0 * k + 2, 11.0 * k + 12) for k in range(13, 40)]
    assert plan_passages(segs) == [PassagePlan(0.0, 142.0), PassagePlan(145.0, 298.0), PassagePlan(299.0, 441.0)]


def test_a_remainder_under_a_minute_is_absorbed():
    # the only boundary (191 s, past the window) would leave a 54 s passage
    assert plan_passages([(0.0, 190.0), (191.0, 245.0)]) == [PassagePlan(0.0, 245.0)]


def test_without_a_boundary_in_the_window_the_first_later_one_is_used():
    assert plan_passages([(0.0, 100.0), (101.0, 250.0), (251.0, 330.0)]) == [PassagePlan(0.0, 250.0), PassagePlan(251.0, 330.0)]


def test_chapters_become_passages_and_a_long_chapter_is_split():
    chapters = [{"title": "开场", "start_time": 0.0, "end_time": 120.0},
                {"title": "正文", "start_time": 120.0, "end_time": 770.0},
                {"title": "空", "start_time": 770.0, "end_time": 800.0}]          # no speech: no passage
    plans = plan_passages(_uniform(70), chapters)                                    # 0 … 769 s
    assert plans[0] == PassagePlan(0.0, 120.0, "开场")
    rest = plans[1:]
    assert len(rest) >= 3 and [p.title for p in rest] == [f"正文 ({i}/{len(rest)})" for i in range(1, len(rest) + 1)]
    assert rest[0].start_s == 121.0 and rest[-1].end_s == 769.0


def test_no_segments_means_no_passages():
    assert plan_passages([]) == []
    assert plan_passages([], [{"title": "x", "start_time": 0.0, "end_time": 500.0}]) == []


def test_a_single_segment_longer_than_the_window_is_one_passage():
    assert plan_passages([(0.0, 400.0)]) == [PassagePlan(0.0, 400.0)]


def test_all_pauses_equal_cuts_nearest_150_s_and_covers_every_segment():
    segs = _uniform(60)                                                              # 0 … 659 s
    plans = plan_passages(segs)
    assert plans[0].start_s == 0.0 and plans[-1].end_s == 659.0
    for a, b in zip(plans, plans[1:]):
        assert a.end_s < b.start_s and b.start_s - a.start_s <= 180.0
    assert all(p.end_s - p.start_s >= 60.0 for p in plans)


def test_chapters_that_do_not_cover_the_audio_still_cover_every_segment():
    # speech before the first chapter joins it; speech after the last chapter's end stays in the last chapter
    chapters = [{"title": "甲", "start_time": 60.0, "end_time": 150.0}, {"title": "乙", "start_time": 150.0, "end_time": 200.0}]
    plans = plan_passages(_uniform(30), chapters)                                    # 0 … 329 s
    assert plans == [PassagePlan(0.0, 153.0, "甲"), PassagePlan(154.0, 329.0, "乙")]


def test_passage_index_is_by_start_time():
    starts = [0.0, 145.0, 299.0]
    assert [passage_index(starts, t) for t in (-1.0, 0.0, 144.9, 145.0, 500.0)] == [0, 0, 0, 1, 2]


def test_default_title():
    assert default_title(3, 125.4, 300.0) == "Passage 4 · 02:05–05:00"


def test_passage_views_membership_and_done():
    plans = [PassagePlan(0.0, 10.0, "A"), PassagePlan(12.0, 20.0, None)]
    views = passage_views(plans, [(1, 0.0, 2), (2, 5.0, 1), (3, 11.0, 1), (4, 12.0, 0), (5, 15.0, 3)])
    assert [(v.idx, v.title, v.segment_ids, v.done) for v in views] == [
        (0, "A", [1, 2, 3], True), (1, "Passage 2 · 00:12–00:20", [4, 5], False)]
    assert passage_views([], [(1, 0.0, 1)]) == []


def test_rebuild_replaces_rows_and_uses_youtube_chapters(data_dir):
    engine = make_engine(data_dir); init_db(engine)
    with Session(engine) as db:
        lesson = Lesson(title="t", source_type="youtube", source_ref="youtube::x",
                        meta_json={"chapters": [{"title": "开场", "start_time": 0.0, "end_time": 120.0},
                                                {"title": "正文", "start_time": 120.0, "end_time": 300.0}]})
        db.add(lesson); db.commit(); db.refresh(lesson)
        for k, (a, b) in enumerate(_uniform(27)):                                    # 0 … 296 s
            db.add(Segment(lesson_id=lesson.id, idx=k, start_s=a, end_s=b, text="你好"))
        db.add(Passage(lesson_id=lesson.id, idx=0, title="old", start_s=0.0, end_s=1.0))
        db.commit()
        lid = lesson.id
    rebuild_passages(engine, lid)
    with Session(engine) as db:
        rows = db.exec(select(Passage).where(Passage.lesson_id == lid).order_by(Passage.idx)).all()
    assert [(p.idx, p.title, p.start_s, p.end_s) for p in rows] == [(0, "开场", 0.0, 120.0), (1, "正文", 121.0, 296.0)]
    rebuild_passages(engine, 999)                                                   # a deleted lesson: nothing happens
