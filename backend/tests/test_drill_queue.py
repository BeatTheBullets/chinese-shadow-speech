import pytest
from sqlmodel import Session
from shadow.config import DrillCfg
from shadow.drill.queue import build_queue, queue_from_ids, targets_for, went_green
from shadow.store.models import Attempt, DrillSession, Lesson, Segment, SyllableScore


def syl(ch, tone):
    return {"ch": ch, "pinyin": ch, "pinyin_toneless": ch, "tone": tone}


def seg(db, lesson, idx, tones, text=None, clip=True):
    chars = text or "".join(chr(0x4E00 + idx * 20 + i) for i in range(len(tones)))
    s = Segment(lesson_id=lesson.id, idx=idx, start_s=idx, end_s=idx + 1, text=chars, clip_wav_path="c.wav" if clip else None,
                words_json=[{"word": chars, "pinyin": "", "tones": tones, "char_from": 0, "char_to": len(chars),
                             "syllables": [syl(c, t) for c, t in zip(chars, tones)]}])
    db.add(s); db.commit(); db.refresh(s); return s


def lesson(db, status="ready"):
    les = Lesson(title="L", source_type="upload", status=status); db.add(les); db.commit(); db.refresh(les); return les


@pytest.fixture
def db(client):
    with Session(client.app.state.engine) as s:
        yield s


def test_targets_for():
    s = [syl("a", 3), syl("b", 3), syl("c", 4), syl("在", 4)]
    assert targets_for(s, "tone", "3") == [0, 1]
    assert targets_for(s, "pair", "3-3") == [1]
    assert targets_for(s, "pair", "3-4") == [2]
    assert targets_for(s, "char", "在") == [3]


def test_queue_contains_focus_respects_length_and_cap(db):
    l1, l2 = lesson(db), lesson(db)
    for i in range(6):
        seg(db, l1, i, [3, 3, 1, 2, 4])                 # 2 targets each
    for i in range(3):
        seg(db, l2, i, [1, 3, 1, 2])                    # 1 target each
    seg(db, l2, 3, [3, 3, 1])                           # too short (3 syllables)
    seg(db, l2, 4, [1, 2, 1, 2, 4])                     # no target
    q = build_queue(db, DrillCfg(queue_size=6), "tone", "3")      # l1 ranks higher (2 targets) but is capped at 4
    lessons = [s.lesson_id for s, _ in q]
    assert len(q) == 6 and lessons.count(l1.id) == 4 and lessons.count(l2.id) == 2
    assert all(t for _, t in q) and [(s.lesson_id, s.idx) for s, _ in q] == sorted((s.lesson_id, s.idx) for s, _ in q)


def test_queue_fills_beyond_the_cap_when_no_other_lesson_has_material(db):
    l1 = lesson(db)
    for i in range(6):
        seg(db, l1, i, [3, 1, 2, 4])
    assert len(build_queue(db, DrillCfg(), "tone", "3")) == 6


def test_queue_skips_lessons_that_are_not_ready_and_segments_without_clips(db):
    seg(db, lesson(db, status="processing"), 0, [3, 1, 2, 4])
    seg(db, lesson(db), 0, [3, 1, 2, 4], clip=False)
    assert build_queue(db, DrillCfg(), "tone", "3") == []


def test_recently_green_sentences_are_skipped(db):
    l1 = lesson(db)
    a, b = seg(db, l1, 0, [3, 1, 2, 4]), seg(db, l1, 1, [3, 1, 2, 4])
    ds = DrillSession(kind="tone", key="3", label="x", items_json=[{"segment_id": a.id, "targets": [0]}], ended_at=None)
    db.add(ds); db.commit()
    att = Attempt(segment_id=a.id, mode="drill", audio_path="x.wav", duration_s=1, drill_session_id=ds.id,
                  score_json={"overall": 0.9}); db.add(att); db.commit()
    db.add(SyllableScore(attempt_id=att.id, segment_id=a.id, idx=0, ch="x", pinyin_toneless="x", tone=3, target_tone=3,
                         tone_score=0.9, status="ok")); db.commit()
    assert went_green(db, ds.id, a.id, [0])
    assert [s.id for s, _ in build_queue(db, DrillCfg(), "tone", "3")] == [b.id]


def test_session_from_segment_ids(client, db):
    l1 = lesson(db)
    a = seg(db, l1, 0, [3, 1, 2, 4])
    assert [s.id for s, _ in queue_from_ids(db, [a.id, 9999], "tone", "3")] == [a.id]
    r = client.post("/drill/sessions", json={"kind": "tone", "key": "3", "segment_ids": [9999]})
    assert r.status_code == 404


def test_session_endpoints(client, db):
    l1 = lesson(db)
    seg(db, l1, 0, [3, 1, 2, 4])
    r = client.post("/drill/sessions", json={"kind": "tone", "key": "3"})
    assert r.status_code == 201
    body = r.json()
    assert body["label"] == "tone 3 (low)" and body["short"] is True and body["items"][0]["targets"] == [0]
    assert body["items"][0]["lesson_title"] == "L" and body["items"][0]["segment"]["id"]
    assert client.post("/drill/sessions", json={"kind": "tone", "key": "0"}).status_code == 400
    assert client.post("/drill/sessions", json={"kind": "char", "key": "龘"}).status_code == 404
    ended = client.patch(f"/drill/sessions/{body['id']}", json={"ended": True}).json()
    assert ended["ended_at"] is not None
    assert client.patch("/drill/sessions/9999", json={"ended": True}).status_code == 404
