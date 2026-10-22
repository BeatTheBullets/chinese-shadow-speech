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


def test_a_focus_whose_sentences_all_went_green_lately_is_drilled_again(client, db):
    l1 = lesson(db)
    a = seg(db, l1, 0, [3, 1, 2, 4])
    ds = DrillSession(kind="tone", key="3", label="x", items_json=[{"segment_id": a.id, "targets": [0]}])
    db.add(ds); db.commit(); db.refresh(ds)
    _drill_take(db, ds, a.id, [("ok", 0.9)])
    assert [s.id for s, _ in build_queue(db, DrillCfg(), "tone", "3")] == [a.id]
    assert client.post("/drill/sessions", json={"kind": "tone", "key": "3"}).status_code == 201


def test_queue_ranking(db):
    """2 × targets (max 3) + 2 × (1 − last score) if practised, + 1 if never: queue_size 1 shows the winner. Each
    pair is its own tone (neutral fillers are never a target), the loser created first so the id tiebreak can't explain it."""
    les = lesson(db)

    def scored(idx, tones, overall):
        s = seg(db, les, idx, tones)
        db.add(Attempt(segment_id=s.id, mode="echo", audio_path="x.wav", duration_s=1, score_json={"overall": overall}))
        db.commit(); return s

    top = lambda key: [s.id for s, _ in build_queue(db, DrillCfg(queue_size=1, max_per_lesson=10), "tone", key)]
    seg(db, les, 0, [1, 0, 0, 0]); more = scored(1, [1, 1, 0, 0], 1.0)           # 3 vs 4: more targets first
    assert top("1") == [more.id]
    scored(2, [2, 0, 0, 0], 0.8); lower = scored(3, [2, 0, 0, 0], 0.2)           # 2.4 vs 3.6: lower last score first
    assert top("2") == [lower.id]
    scored(4, [4, 0, 0, 0], 0.6); fresh = seg(db, les, 5, [4, 0, 0, 0])          # 2.8 vs 3: never practised +1
    assert top("4") == [fresh.id]


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
    assert body["max_tries"] == 3
    client.app.state.settings.drill.max_tries = 2                    # [drill] max_tries reaches the runner
    assert client.post("/drill/sessions", json={"kind": "tone", "key": "3"}).json()["max_tries"] == 2
    assert client.post("/drill/sessions", json={"kind": "tone", "key": "0"}).status_code == 400
    assert client.post("/drill/sessions", json={"kind": "char", "key": "龘"}).status_code == 404
    ended = client.patch(f"/drill/sessions/{body['id']}", json={"ended": True}).json()
    assert ended["ended_at"] is not None
    assert client.patch("/drill/sessions/9999", json={"ended": True}).status_code == 404


def _drill_take(db, ds, seg_id, statuses_scores, overall=0.5):
    att = Attempt(segment_id=seg_id, mode="drill", audio_path="x.wav", duration_s=1, drill_session_id=ds.id,
                  score_json={"overall": overall}); db.add(att); db.commit()
    for i, (st, sc) in enumerate(statuses_scores):
        db.add(SyllableScore(attempt_id=att.id, segment_id=seg_id, idx=i, ch="x", pinyin_toneless="x", tone=3,
                             target_tone=3, tone_score=sc, status=st))
    db.commit(); return att


def test_target_mean():
    from shadow.drill.summary import target_mean
    rows = {0: ("ok", 0.9), 1: ("missing", None), 2: ("unvoiced", None), 3: ("close", 0.5)}
    assert target_mean(rows, [0, 1, 2]) == (pytest.approx(0.45), 1)
    assert target_mean(rows, [2]) == (None, 0)


def test_summary_first_best_tries_and_history(client, db):
    l1 = lesson(db)
    a = seg(db, l1, 0, [3, 1, 3, 4])
    ds = DrillSession(kind="tone", key="3", label="tone 3 (low)", items_json=[{"segment_id": a.id, "targets": [0, 2]}])
    db.add(ds); db.commit(); db.refresh(ds)
    _drill_take(db, ds, a.id, [("close", 0.4), ("ok", 0.9), ("close", 0.5), ("ok", 0.9)])
    gated = Attempt(segment_id=a.id, mode="drill", audio_path="x.wav", duration_s=1, drill_session_id=ds.id,
                    score_json={"overall": None, "warnings": ["too_quiet"]}); db.add(gated); db.commit()
    best = _drill_take(db, ds, a.id, [("ok", 0.8), ("ok", 0.9), ("ok", 0.9), ("ok", 0.9)])
    client.patch(f"/drill/sessions/{ds.id}", json={"ended": True})
    s = client.get(f"/drill/sessions/{ds.id}/summary").json()
    it = s["items"][0]
    assert it["tries"] == 2 and it["went_green"] is True and it["best"]["attempt_id"] == best.id
    assert it["first"]["mean"] == pytest.approx(0.45) and it["first"]["green"] == 0 and it["best"]["green"] == 2
    assert s["first_mean"] == pytest.approx(0.45) and s["best_mean"] == pytest.approx(0.85) and s["n_targets"] == 2
    assert [h["session_id"] for h in s["history"]] == [ds.id]
    assert client.get("/drill/sessions").json()["sessions"][0]["best_mean"] == pytest.approx(0.85)


def test_drills_without_takes_are_left_out_of_recent_and_history(client, db):
    a = seg(db, lesson(db), 0, [3, 1, 2, 4])
    real = DrillSession(kind="tone", key="3", label="x", items_json=[{"segment_id": a.id, "targets": [0]}])
    empty = DrillSession(kind="tone", key="3", label="x", items_json=[{"segment_id": a.id, "targets": [0]}])
    db.add(real); db.add(empty); db.commit(); db.refresh(real); db.refresh(empty)
    _drill_take(db, real, a.id, [("close", 0.5)])
    for ds in (real, empty):
        client.patch(f"/drill/sessions/{ds.id}", json={"ended": True})
    assert [s["id"] for s in client.get("/drill/sessions").json()["sessions"]] == [real.id]
    assert [h["session_id"] for h in client.get(f"/drill/sessions/{real.id}/summary").json()["history"]] == [real.id]


def test_summary_skips_deleted_segments(client, db):
    ds = DrillSession(kind="tone", key="3", label="x", items_json=[{"segment_id": 9999, "targets": [0]}])
    db.add(ds); db.commit(); db.refresh(ds)
    assert client.get(f"/drill/sessions/{ds.id}/summary").json()["items"] == []
    assert client.get("/drill/sessions/9999/summary").status_code == 404


PY = {"她": "ta", "喜": "xi", "欢": "huan", "吃": "chi", "苹": "ping", "果": "guo"}


def _sound_syls():
    return [{"ch": c, "pinyin": p, "pinyin_toneless": p.upper() if c == "吃" else p, "tone": 1} for c, p in PY.items()]


def test_sound_targets():
    s = _sound_syls()
    assert targets_for(s, "sound", "ch>c") == [3]       # case differences in pinyin_toneless are ignored
    assert targets_for(s, "sound", "ng>n") == [4]


def _sound_take(db, ds, seg_id, statuses):
    att = Attempt(segment_id=seg_id, mode="drill", audio_path="x.wav", duration_s=1, drill_session_id=ds.id,
                  score_json={"overall": 0.5}); db.add(att); db.commit()
    for i, st in enumerate(statuses):
        db.add(SyllableScore(attempt_id=att.id, segment_id=seg_id, idx=i, ch="x", pinyin_toneless="chi", tone=1,
                             tone_score=0.9, status="ok", sound_status=st))
    db.commit(); return att


def test_sound_green_needs_every_target_checked_ok(db):
    les = lesson(db); a = seg(db, les, 0, [1, 1, 1])
    ds = DrillSession(kind="sound", key="ch>c", label="x", items_json=[{"segment_id": a.id, "targets": [0, 1]}])
    db.add(ds); db.commit(); db.refresh(ds)
    _sound_take(db, ds, a.id, ["ok", None, "ok"])
    assert went_green(db, ds.id, a.id, [0, 1], kind="sound") is False
    assert went_green(db, ds.id, a.id, [0, 1]) is True          # tone kind still reads status
    _sound_take(db, ds, a.id, ["ok", "ok", "slip"])
    assert went_green(db, ds.id, a.id, [0, 1], kind="sound") is True


def test_sound_summary_mean_is_share_ok(client, db):
    from shadow.drill.summary import target_mean
    assert target_mean({0: "ok", 1: "slip"}, [0, 1, 2], "sound") == (pytest.approx(1 / 3), 1)
    les = lesson(db); a = seg(db, les, 0, [1, 1, 1])
    ds = DrillSession(kind="sound", key="ch>c", label="x", items_json=[{"segment_id": a.id, "targets": [0, 1]}])
    db.add(ds); db.commit(); db.refresh(ds)
    _sound_take(db, ds, a.id, ["ok", "slip", "ok"])
    client.patch(f"/drill/sessions/{ds.id}", json={"ended": True})
    it = client.get(f"/drill/sessions/{ds.id}/summary").json()["items"][0]
    assert it["first"]["mean"] == pytest.approx(0.5) and it["first"]["green"] == 1 and it["went_green"] is False
