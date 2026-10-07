# YouTube Lessons, Passages, Listening Cards and Practice Guidance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a YouTube video the primary lesson source (sent from Brave in one step), split every lesson into 2–3 minute passages, tell the learner what to do at every moment of practice (cue line, karaoke wipes, count-in, adjustable volume), and turn practised sentences into Anki listening cards in one click — after repairing alignment spans and making a syllable click play once.

**Architecture:** Backend: a pure alignment-repair module applied wherever spans are produced (ingest and re-enrich); a `youtube` ingest module (link parsing, Chinese subtitle choice, readable errors, a `Downloader` protocol with a yt-dlp and a fake implementation) that feeds the existing upload pipeline; a `passages` module (pure planner, rebuild, membership by start time) with a `Passage` table; a `review` router for practised sentences not in Anki. Frontend: pure helpers in `src/lib` (cue, karaoke timing, volume, passages, filler detection, hand-off) carry the logic and are unit-tested; components (cue line, karaoke overlay, help overlay, export list and dialog) stay thin; `Practice.tsx` and `useFlow.ts` wire them in.

**Tech Stack:** Python 3.12, uv, FastAPI, SQLModel/SQLite, rapidfuzz, yt-dlp (Python API), pytest; React 18, Vite 5, TypeScript 5.6, zustand, Tailwind 3, vitest + Testing Library, AnkiConnect (from the browser).

**Spec:** `docs/superpowers/specs/2026-10-07-youtube-passages-guidance-design.md` (binding). It amends `docs/superpowers/specs/2026-10-03-shadowing-tool-design.md`; read §3 (pipeline), §4 (data model), §6 (modes), §7 (frontend, especially §7.7 Yomitan) and §8 (Anki) there for context.

## Global Constraints

- Backend commands run from `backend/` with `~/.local/bin/uv run …`; frontend commands from `frontend/` (Node 20). `make test` (backend pytest without `models`, vitest, eslint) must be green at the end of every task.
- TypeScript targets ES2020: no `Array.prototype.at`, no `String.prototype.replaceAll`. ESLint's `@typescript-eslint/no-unused-vars` is an error: remove imports you stop using.
- Tests never touch the network, a GPU or a model download. YouTube goes through `FakeDownloader`; the MMS_FA comparison is a manual script.
- Everything shown is simplified Chinese: video titles, channel names (speaker) and chapter titles go through `to_simplified` (OpenCC t2s).
- Yomitan (main spec §7.7, hard requirement): the sentence stays one `<p lang="zh">` with one `<ruby>` per word, no per-character elements, no shadow DOM, no canvas text, no `user-select: none`. Wipes are a separate `aria-hidden`, `pointer-events: none` layer outside the `<p>`.
- Alignment repair (addendum §1.1): a span shorter than 40 ms, or starting more than 0.3 s from its coarse start, takes the coarse span; then spans are made monotonic; conf: aligner 1.0, repaired 0.5, uniform fallback 0.0. Without coarse times a zero-length span takes the gap up to the next span's start, split evenly among consecutive zero-length spans.
- Passages (addendum §4): target 150 s, cut at the largest pause within 120–180 s, a remainder under 60 s is absorbed, lessons shorter than 4 min have one passage, chapters longer than 4 min are split; default title `Passage N · mm:ss–mm:ss`; a segment belongs to the passage whose time range contains its `start_s`; done = every segment in it has at least one attempt.
- YouTube (addendum §2): `POST /lessons/youtube {url}` → `{job_id, lesson_id}`; `source_ref = "youtube::<id>"`; an existing lesson is returned with no job unless it is in `error`; `[youtube] enabled = true`, `max_minutes = 90`, `cookies_file = ""`; first progress stage `download`; subtitle preference manual `zh-Hans`, then `zh-Hant`/`zh-TW`/`zh`, then auto-generated `zh-Hans`/`zh`; English and other languages are never downloaded.
- Error wording (addendum §2): sign-in/age/bot check → "this video needs a cookies file — see Settings"; outdated yt-dlp → "update yt-dlp: `cd backend && uv lock --upgrade-package yt-dlp && uv sync --extra dev --extra models`".
- Anki (addendum §5.1): deck `shadow-speech`, note type `Shadow Listening`, fields `Audio, Sentence, Pinyin, Translation, Source, Link`; `Source` = "<lesson title> · mm:ss", `Link` = the YouTube URL with `&t=<seconds>` (empty otherwise); tags `shadow`, `shadow::<lesson id>`; an existing deck/note type is reused, never modified; AnkiConnect errors are shown verbatim after a short explanation.
- Fillers (addendum §5.2): fewer than 4 speech characters, or made only of 嗯 啊 哦 呃 对 好 是 嗯嗯 对对 好的 是的.
- Mode tooltips and cue texts are copied verbatim from addendum §6.1 and §6.2.
- Volume (addendum §7): reference 0–100 %, default 100 %, applied to every reference playback; guide level default 50 % of the reference volume, only in Chorus and Flow *along*; your own takes play at the reference volume.
- New frontend settings keys (top level of the persisted `shadow.settings` zustand store): `referenceVolume`, `guideLevel`, `helpSeen`.
- Never stage the stray untracked files `frontend/src/deckNames`, `frontend/src/findNotes`, `frontend/src/modelNames`: `git add` files by name.

## Review Focus

1. **A YouTube link with extra parameters or from another URL form** (`m.youtube.com/watch?v=…&list=…&index=2`, `youtu.be/ID?si=…&t=10`, `youtube.com/shorts/ID?feature=share`) must resolve to the same video and dedupe against the existing lesson. Tests: Task 5 `test_parse_video_id_accepts_watch_short_and_shorts_links`, Task 6 `test_adding_the_same_video_again_returns_its_lesson_without_a_job` (adds the second time with a different URL form).
2. **A lesson created before this change has no Passage rows**: it must still show passages in Practice and "n / m passages" on its tile, without a re-ingest. Test: Task 9 `test_lesson_without_passage_rows_gets_computed_passages`.
3. **A sentence with no usable alignment** (alignment failed → `[]`, or `null`) must render with no wipe while the cue line still shows, and nothing throws. Tests: Task 11 `wipeProgress`/`stageWipe` on empty spans, Task 13 `<KaraokeSentence>` "draws nothing" test.
4. **Anki closed during the session-end send**: each row shows its own error, nothing is marked sent, the rows stay ticked for a retry, and the server keeps listing them as practised-not-in-Anki. Tests: Task 17 `<ExportList>` "Anki unreachable" test, Task 15 `test_unexported_lists_practised_sentences_without_a_note_newest_first` (only `anki_note_id` removes a row).
5. **The bookmarklet page `/library?add=…` effect running twice** (React StrictMode double effects, a reload): it must ask once and submit once, and declining must still clear the parameter. Tests: Task 7 Library tests rendered inside `<StrictMode>`.

---

### Task 1: Backend — alignment repair module

**Files:**
- Create: `backend/shadow/ingest/repair.py`
- Test: `backend/tests/test_repair.py`

**Interfaces:**
- Consumes: `Span(ch: str, start: float, end: float, conf: float)` from `shadow.ingest.align`; `TimedChar(c: str, start: float, end: float)` from `shadow.ingest.transcript`; `is_punct(ch) -> bool` from `shadow.ingest.text`.
- Produces (used by Tasks 2 and 3):
  - `MIN_SPAN_S = 0.04`, `MAX_START_DRIFT_S = 0.3`, `REPAIRED_CONF = 0.5`, `Times = tuple[float, float]`
  - `coarse_times(text: str, chars: list[TimedChar]) -> list[Times | None]` — one entry per speech character of `text`
  - `make_monotonic(spans: list[Span]) -> list[Span]`
  - `fill_gaps(spans: list[Span]) -> list[Span]`
  - `repair_spans(spans: list[Span], coarse: list[Times | None] | None = None) -> list[Span]`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_repair.py`:
```python
from shadow.ingest.align import Span
from shadow.ingest.repair import REPAIRED_CONF, coarse_times, repair_spans
from shadow.ingest.transcript import TimedChar


def _t(spans):
    return [(round(s.start, 3), round(s.end, 3), s.conf) for s in spans]


def test_coarse_times_match_speech_chars_and_skip_punctuation():
    chars = [TimedChar("我", 8.63, 8.87), TimedChar("，", 8.87, 8.87), TimedChar("好", 8.9, 9.1)]
    assert coarse_times("我，好。", chars) == [(8.63, 8.87), (8.9, 9.1)]


def test_coarse_times_line_up_edited_text_and_leave_added_chars_none():
    # the LLM repaired 雪 → 学 (a substitution keeps its time) and added 啊 (no ASR char)
    chars = [TimedChar(c, i * 0.2, i * 0.2 + 0.2) for i, c in enumerate("我雪中文")]
    assert coarse_times("我学中文啊", chars) == [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), None]


def test_zero_length_span_takes_the_coarse_span_with_conf_half():
    spans = [Span("我", 7.63, 7.63, 1.0), Span("好", 8.9, 9.1, 1.0)]
    assert _t(repair_spans(spans, [(8.63, 8.87), (8.9, 9.1)])) == [(8.63, 8.87, REPAIRED_CONF), (8.9, 9.1, 1.0)]


def test_span_starting_too_early_takes_the_coarse_span():
    # lesson 1, sentence 0: Qwen3 starts 我 a second early (7.63–8.59); the ASR has it at 8.63–8.87
    spans = [Span("我", 7.63, 8.59, 1.0), Span("今", 8.88, 9.1, 1.0)]
    assert _t(repair_spans(spans, [(8.63, 8.87), (8.87, 9.1)])) == [(8.63, 8.87, 0.5), (8.88, 9.1, 1.0)]


def test_small_drift_and_missing_coarse_keep_the_aligner_span():
    spans = [Span("我", 1.2, 1.4, 1.0), Span("好", 1.4, 1.6, 1.0)]
    assert repair_spans(spans, [(1.0, 1.3), None]) == spans          # 0.2 s drift is within 0.3 s


def test_repaired_spans_are_made_monotonic():
    # the coarse span of 我 ends after the aligner's start of 好
    spans = [Span("我", 0.0, 0.0, 1.0), Span("好", 0.3, 0.6, 1.0)]
    out = repair_spans(spans, [(0.2, 0.4), (0.35, 0.6)])
    assert _t(out) == [(0.2, 0.4, 0.5), (0.4, 0.6, 1.0)]
    for a, b in zip(out, out[1:]):
        assert a.start <= a.end <= b.start <= b.end


def test_without_coarse_times_zero_length_spans_share_the_gap_to_the_next_span():
    # Anki segments have no transcript: two zero-length chars before a span at 1.0 split 0.4–1.0 evenly
    spans = [Span("你", 0.1, 0.4, 1.0), Span("好", 0.4, 0.4, 1.0), Span("吗", 0.4, 0.4, 0.0), Span("呀", 1.0, 1.3, 1.0)]
    assert _t(repair_spans(spans)) == [(0.1, 0.4, 1.0), (0.4, 0.7, 0.5), (0.7, 1.0, 0.5), (1.0, 1.3, 1.0)]


def test_zero_length_last_span_without_a_next_one_stays():
    spans = [Span("你", 0.1, 0.4, 1.0), Span("好", 0.4, 0.4, 1.0)]
    assert _t(repair_spans(spans)) == [(0.1, 0.4, 1.0), (0.4, 0.4, 1.0)]


def test_empty_spans_and_coarse_of_the_wrong_length_are_tolerated():
    assert repair_spans([], []) == []
    spans = [Span("你", 0.0, 0.0, 1.0), Span("好", 0.5, 0.8, 1.0)]
    # one coarse time for two spans: treated as no coarse times (gap fill only)
    assert _t(repair_spans(spans, [(9.0, 9.5)])) == [(0.0, 0.5, 0.5), (0.5, 0.8, 1.0)]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_repair.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadow.ingest.repair'`

- [ ] **Step 3: Write the implementation**

`backend/shadow/ingest/repair.py`:
```python
"""Repair of forced-alignment spans against coarse character times (addendum spec §1.1).

The Qwen3 aligner predicts boundaries on an 80 ms grid and often returns a zero-length span for a character, or starts
a sentence's first character up to ~1 s before the speech. The coarse times of the same characters (the ASR's, or for
subtitle text the subalign times) are consistent, so a span shorter than MIN_SPAN_S or starting more than
MAX_START_DRIFT_S from its coarse start takes the coarse span (conf REPAIRED_CONF; aligner spans are 1.0, the uniform
fallback 0.0). Spans are then made monotonic, and any span still shorter than MIN_SPAN_S (no coarse time: Anki
segments, or a character an edit added) shares the gap up to the next span with its zero-length neighbours."""
from __future__ import annotations
from rapidfuzz.distance import Levenshtein
from shadow.ingest.align import Span
from shadow.ingest.text import is_punct
from shadow.ingest.transcript import TimedChar

MIN_SPAN_S = 0.04
MAX_START_DRIFT_S = 0.3
REPAIRED_CONF = 0.5

Times = tuple[float, float]


def coarse_times(text: str, chars: list[TimedChar]) -> list[Times | None]:
    """Per speech character of `text`, the time of the character it lines up with in `chars` (punctuation ignored on
    both sides) under a character edit alignment: equal and substituted characters match, added ones get None."""
    speech = [c for c in text if not is_punct(c)]
    coarse = [c for c in chars if not is_punct(c.c)]
    out: list[Times | None] = [None] * len(speech)
    for op in Levenshtein.opcodes("".join(speech), "".join(c.c for c in coarse)):
        if op.tag in ("equal", "replace"):                  # rapidfuzz replace blocks are 1:1
            for i, j in zip(range(op.src_start, op.src_end), range(op.dest_start, op.dest_end)):
                out[i] = (coarse[j].start, coarse[j].end)
    return out


def make_monotonic(spans: list[Span]) -> list[Span]:
    """Each span starts no earlier than the previous one ends, and ends no earlier than it starts."""
    out: list[Span] = []
    prev_end: float | None = None
    for sp in spans:
        start = sp.start if prev_end is None else max(sp.start, prev_end)
        end = max(sp.end, start)
        out.append(sp if (start, end) == (sp.start, sp.end) else Span(sp.ch, start, end, sp.conf))
        prev_end = end
    return out


def fill_gaps(spans: list[Span]) -> list[Span]:
    """Runs of spans shorter than MIN_SPAN_S share, evenly, the time from the run's start to the next span's start
    (conf REPAIRED_CONF). A run with no later span, or no time before it, is left as it is. Expects monotonic spans."""
    out = list(spans)
    i = 0
    while i < len(out):
        if out[i].end - out[i].start >= MIN_SPAN_S:
            i += 1
            continue
        j = i
        while j + 1 < len(out) and out[j + 1].end - out[j + 1].start < MIN_SPAN_S:
            j += 1
        if j + 1 < len(out) and out[j + 1].start > out[i].start:
            t0, n, t1 = out[i].start, j - i + 1, out[j + 1].start
            step = (t1 - t0) / n
            for m, k in enumerate(range(i, j + 1)):
                out[k] = Span(out[k].ch, t0 + m * step, t1 if m == n - 1 else t0 + (m + 1) * step, REPAIRED_CONF)
        i = j + 1
    return out


def repair_spans(spans: list[Span], coarse: list[Times | None] | None = None) -> list[Span]:
    """`spans` checked against the coarse times of the same characters as the module docstring describes. `coarse`
    None, or of a different length than `spans`, means no coarse times (gap fill only)."""
    if coarse is None or len(coarse) != len(spans):
        coarse = [None] * len(spans)
    replaced = [Span(sp.ch, c[0], c[1], REPAIRED_CONF)
                if c is not None and (sp.end - sp.start < MIN_SPAN_S or abs(sp.start - c[0]) > MAX_START_DRIFT_S)
                else sp
                for sp, c in zip(spans, coarse)]
    return fill_gaps(make_monotonic(replaced))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_repair.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: Commit**

```bash
git add backend/shadow/ingest/repair.py backend/tests/test_repair.py
git commit -m "feat(backend): repair alignment spans against coarse character times"
```

---

### Task 2: Backend — apply the repair in ingest and re-enrich

**Files:**
- Modify: `backend/shadow/ingest/pipeline.py` (imports; the align loop in `build_segments`)
- Modify: `backend/shadow/ingest/reenrich.py` (imports; new `_coarse`; `reenrich_segment`)
- Test: `backend/tests/test_pipeline.py` (append), `backend/tests/test_segments_api.py` (append)

**Interfaces:**
- Consumes: `coarse_times`, `repair_spans`, `Times` (Task 1); `Transcript.from_json(d) -> Transcript` (existing).
- Produces: every `Segment.ref_alignment_json` written by `build_segments` and `reenrich_segment` is repaired. Test helper `_EarlyZeroLengthStart` in `tests/test_pipeline.py` (reused below).

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_pipeline.py`:
```python
class _EarlyZeroLengthStart:
    """Sentence 1 (其实方法有很多, coarse 3.0–5.0 s, aligned inside 2.0–6.0 s): its first character zero-length and a
    second early, the others on their coarse times. Other sentences as FakeAligner."""

    def align(self, wav, sr, text):
        if not text.startswith("其实"):
            return FakeAligner().align(wav, sr, text)
        step = 2.0 / 7
        spans = [Span(c, 1.0 + k * step, 1.0 + (k + 1) * step, 1.0) for k, c in enumerate("其实方法有很多")]
        spans[0] = Span("其", 0.0, 0.0, 1.0)                 # window-relative 0.0 = 2.0 s in the lesson
        return spans


def test_ingest_repairs_zero_length_and_early_spans_from_the_transcript(data_dir, fake_transcript, tmp_path):
    deps, engine, lid = _setup(data_dir, fake_transcript)
    deps.aligner = _EarlyZeroLengthStart()
    ingest_upload(deps, engine, lid, make_tone_wav(tmp_path / "t.wav", 8.0), None, lambda s, f: None)
    seg = _segments(engine, lid)[1]
    assert seg.ref_alignment_json[0] == {"ch": "其", "start": 3.0, "end": 3.286, "conf": 0.5}
    assert seg.ref_alignment_json[1]["conf"] == 1.0
    assert (seg.start_s, seg.end_s) == (3.0, 5.0)          # the clip no longer starts a second early


class _ZeroLengthFirstChar:
    def align(self, wav, sr, text):
        spans = FakeAligner().align(wav, sr, text)
        spans[0] = Span(spans[0].ch, spans[0].start, spans[0].start, 1.0)
        return spans


def test_build_segments_with_fixed_spans_fills_zero_length_chars_from_the_gap(data_dir, tmp_path):
    from shadow.ingest import audio
    deps, engine, lid = _setup(data_dir, Transcript())
    deps.aligner = _ZeroLengthFirstChar()
    src = deps.files.source_wav(lid)
    audio.normalise(make_tone_wav(tmp_path / "t.wav", 4.0), src)
    build_segments(deps, engine, lid, src, None, [RectSentenceOut(0, 0, "谢谢你。")], lambda s, f: None,
                   fixed_spans=[(2.0, 3.5)])
    al = _segments(engine, lid)[0].ref_alignment_json
    assert (al[0]["start"], al[0]["end"], al[0]["conf"]) == (2.0, 2.5, 0.5)    # the gap up to the second 谢
    assert (al[1]["start"], al[1]["conf"]) == (2.5, 1.0)
```

Append to `backend/tests/test_segments_api.py`:
```python
def test_reenrich_repairs_spans_from_the_transcript_with_or_without_a_char_range(client, tmp_path):
    from shadow.ingest.reenrich import reenrich_segment
    from tests.test_pipeline import _EarlyZeroLengthStart
    lid = _upload(client, tmp_path)
    sid = _segments(client, lid)[1]["id"]
    deps, engine = client.app.state.deps, client.app.state.engine
    deps.aligner = _EarlyZeroLengthStart()
    reenrich_segment(deps, engine, sid, window=(2.0, 6.0))
    assert _segments(client, lid)[1]["ref_alignment_json"][0] == {"ch": "其", "start": 3.0, "end": 3.286, "conf": 0.5}
    with Session(engine) as db:                              # a resplit half has no transcript char range
        row = db.get(Segment, sid)
        row.char_from = row.char_to = None
        db.add(row); db.commit()
    reenrich_segment(deps, engine, sid, window=(2.0, 6.0))
    al = _segments(client, lid)[1]["ref_alignment_json"]
    assert al[0] == {"ch": "其", "start": 3.0, "end": 3.286, "conf": 0.5} and al[1]["conf"] == 1.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_pipeline.py tests/test_segments_api.py -q -k "repair or fills_zero_length"`
Expected: FAIL — the first character comes back as `{"ch": "其", "start": 2.0, "end": 2.0, "conf": 1.0}`.

- [ ] **Step 3: Apply the repair in `build_segments`**

In `backend/shadow/ingest/pipeline.py` add the import after the `rectify` import:
```python
from shadow.ingest.repair import coarse_times, repair_spans
```
and replace, in the align loop of `build_segments`,
```python
        aligned.append(_align(deps, wav, sr, i, texts[i], *win))
        progress("align", (i + 1) / n)
```
with
```python
        spans = _align(deps, wav, sr, i, texts[i], *win)
        # addendum §1.1: upload text is checked against its transcript chars; Anki segments only get the gap fill
        coarse = None if fixed_spans is not None else coarse_times(texts[i], tr.chars[s.char_from:s.char_to + 1])
        aligned.append(repair_spans(spans, coarse))
        progress("align", (i + 1) / n)
```

- [ ] **Step 4: Apply the repair in `reenrich_segment`**

In `backend/shadow/ingest/reenrich.py` add the imports:
```python
from shadow.ingest.repair import Times, coarse_times, repair_spans
from shadow.ingest.transcript import Transcript
```
add above `reenrich_segment`:
```python
def _coarse(lesson: Lesson, seg: Segment, window: tuple[float, float]) -> list[Times | None] | None:
    """Coarse char times for the re-aligned `seg.text` (addendum §1.1): its transcript char range, or, for a segment
    that lost it in a resplit, the transcript chars starting inside the alignment window. None without a transcript
    (Anki lessons)."""
    if lesson.source_type == "anki" or not lesson.transcript_json:
        return None
    chars = Transcript.from_json(lesson.transcript_json).chars
    if seg.char_from is not None and seg.char_to is not None:
        chars = chars[seg.char_from:seg.char_to + 1]
    else:
        chars = [c for c in chars if window[0] <= c.start <= window[1]]
    return coarse_times(seg.text, chars)
```
and in `reenrich_segment` replace
```python
        fixed = db.get(Lesson, seg.lesson_id).source_type == "anki"
```
with
```python
        lesson = db.get(Lesson, seg.lesson_id)
        fixed = lesson.source_type == "anki"
```
and
```python
        spans = _align(deps, wav, sr, seg.idx, seg.text, *window)
```
with
```python
        spans = repair_spans(_align(deps, wav, sr, seg.idx, seg.text, *window), _coarse(lesson, seg, window))
```

- [ ] **Step 5: Run the new tests, then the whole backend suite**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_pipeline.py tests/test_segments_api.py -q -k "repair or fills_zero_length"`
Expected: PASS (3 passed)

Run: `cd backend && ~/.local/bin/uv run pytest -q`
Expected: all pass. The repair also changes FakeAligner spans in existing tests (FakeAligner spreads a sentence over its ±1 s window, so most of its spans drift more than 0.3 s from the coarse times and are replaced); the existing assertions are about order and coverage and should still hold. If one that asserts an exact time fails, recompute that time from the rule above, change only that number, and say so in the commit message.

- [ ] **Step 6: Commit**

```bash
git add backend/shadow/ingest/pipeline.py backend/shadow/ingest/reenrich.py backend/tests/test_pipeline.py backend/tests/test_segments_api.py
git commit -m "feat(backend): repair alignment spans in ingest and re-enrich"
```

---

### Task 3: Backend — MMS_FA comparison script and the aligner decision

**Files:**
- Create: `backend/shadow/ingest/aligncheck.py`, `backend/scripts/compare_aligners.py`
- Test: `backend/tests/test_aligncheck.py`
- Modify only if the verdict is `mms_fa` (Step 6): `backend/shadow/config.py`, `backend/tests/test_config.py`, `config.toml`, `docs/running.md`
- Modify: this plan's **Ledger** section (bottom of this file)

**Interfaces:**
- Consumes: `coarse_times`, `repair_spans` (Task 1); `align_in_window`, `make_aligner`, `Span` (existing `shadow.ingest.align`).
- Produces: `energy_onset(wav, sr, start, end, rel=0.15) -> float | None`; `zero_length_share(sentences: list[list[Span]]) -> float`; `OnsetError(n, mean_ms, median_ms, within_100ms)`; `onset_error(predicted, truth) -> OnsetError`; `verdict(qwen: OnsetError, qwen_zero: float, mms: OnsetError, mms_zero: float) -> str` (`"mms_fa"` or `"qwen3_fa"`).

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_aligncheck.py`:
```python
import numpy as np
from shadow.ingest.align import Span
from shadow.ingest.aligncheck import OnsetError, energy_onset, onset_error, verdict, zero_length_share


def test_energy_onset_finds_the_first_loud_frame():
    sr = 16000
    wav = np.zeros(sr * 2, dtype="float32")
    wav[int(0.8 * sr):int(1.5 * sr)] = 0.3 * np.sin(np.arange(int(0.7 * sr)) * 0.2)
    assert abs(energy_onset(wav, sr, 0.0, 2.0) - 0.8) <= 0.02
    assert energy_onset(np.zeros(sr, dtype="float32"), sr, 0.0, 1.0) is None     # silence
    assert energy_onset(wav, sr, 1.99, 2.0) is None                               # shorter than one frame


def test_zero_length_share():
    assert zero_length_share([[Span("我", 1.0, 1.0, 1.0), Span("好", 1.0, 1.2, 1.0)], []]) == 0.5
    assert zero_length_share([]) == 0.0


def test_onset_error_skips_missing_values():
    e = onset_error([1.05, None, 2.5], [1.0, 3.0, 2.0])
    assert (e.n, e.mean_ms, e.median_ms, e.within_100ms) == (2, 275.0, 275.0, 0.5)


def test_verdict_needs_mms_clearly_better():
    q = OnsetError(50, 200.0, 150.0, 0.4)
    assert verdict(q, 0.3, OnsetError(50, 120.0, 90.0, 0.7), 0.0) == "mms_fa"
    assert verdict(q, 0.3, OnsetError(50, 150.0, 90.0, 0.7), 0.0) == "qwen3_fa"     # only 25 % better
    assert verdict(q, 0.0, OnsetError(50, 100.0, 90.0, 0.7), 0.1) == "qwen3_fa"     # more zero-length spans
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_aligncheck.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadow.ingest.aligncheck'`

- [ ] **Step 3: Write the metrics module**

`backend/shadow/ingest/aligncheck.py`:
```python
"""Metrics for comparing forced aligners on a real lesson (addendum spec §1.1); used by scripts/compare_aligners.py."""
from __future__ import annotations
import statistics
from dataclasses import dataclass
import numpy as np
from shadow.ingest.align import Span

FRAME_S = 0.02


def energy_onset(wav: np.ndarray, sr: int, start: float, end: float, rel: float = 0.15) -> float | None:
    """Start of the first 20 ms frame in [start, end) whose RMS reaches `rel` × the loudest frame there; None for a
    window shorter than one frame or a silent one."""
    n = int(FRAME_S * sr)
    a, b = max(0, int(start * sr)), min(len(wav), int(end * sr))
    if b - a < n:
        return None
    frames = wav[a:a + (b - a) // n * n].reshape(-1, n).astype("float64")
    rms = np.sqrt((frames ** 2).mean(axis=1))
    if rms.max() <= 0:
        return None
    k = int(np.argmax(rms >= rel * rms.max()))
    return round((a + k * n) / sr, 3)


def zero_length_share(sentences: list[list[Span]]) -> float:
    """Share of spans shorter than 1 ms across all sentences (0.0 when there are none)."""
    spans = [s for sent in sentences for s in sent]
    return sum(1 for s in spans if s.end - s.start < 0.001) / len(spans) if spans else 0.0


@dataclass
class OnsetError:
    n: int
    mean_ms: float
    median_ms: float
    within_100ms: float          # share of sentences whose onset is within 100 ms of the energy onset


def onset_error(predicted: list[float | None], truth: list[float | None]) -> OnsetError:
    """First-character onset error against the energy onset, over the sentences where both exist."""
    errs = [abs(p - t) * 1000 for p, t in zip(predicted, truth) if p is not None and t is not None]
    if not errs:
        return OnsetError(0, float("nan"), float("nan"), 0.0)
    return OnsetError(len(errs), round(statistics.fmean(errs), 1), round(statistics.median(errs), 1),
                      round(sum(1 for e in errs if e <= 100) / len(errs), 3))


def verdict(qwen: OnsetError, qwen_zero: float, mms: OnsetError, mms_zero: float) -> str:
    """"mms_fa" when MMS_FA is clearly better than the repaired Qwen3 spans (mean onset error at least 30 % lower and
    no more zero-length spans), else "qwen3_fa"."""
    if mms.n and qwen.n and mms.mean_ms <= 0.7 * qwen.mean_ms and mms_zero <= qwen_zero:
        return "mms_fa"
    return "qwen3_fa"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_aligncheck.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: Write the comparison script and check it starts**

`backend/scripts/compare_aligners.py`:
```python
"""Compare Qwen3 (raw and repaired), MMS_FA and the ASR char times on one ingested lesson (addendum spec §1.1).

Run manually, with the models extra installed and a GPU (Qwen3 needs one):
    cd backend && ~/.local/bin/uv run python scripts/compare_aligners.py --lesson 1
Prints, per source, the first-character onset error against an energy onset and the share of zero-length spans,
then a verdict line. MMS_FA downloads ~1.2 GB on first use."""
from __future__ import annotations
import argparse
from sqlmodel import Session, select
from shadow.config import load_settings
from shadow.ingest import audio
from shadow.ingest.align import Span, align_in_window, make_aligner
from shadow.ingest.aligncheck import energy_onset, onset_error, verdict, zero_length_share
from shadow.ingest.repair import coarse_times, repair_spans
from shadow.ingest.text import is_punct
from shadow.ingest.transcript import Transcript
from shadow.store.db import make_engine
from shadow.store.files import FileLayout
from shadow.store.models import Lesson, Segment

MARGIN_S = 1.0          # the same alignment window as the pipeline (spec §3.4)


def main() -> None:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--lesson", type=int, required=True)
    args = ap.parse_args()
    settings = load_settings()
    engine, files = make_engine(settings.data_dir), FileLayout(settings.data_dir)
    with Session(engine) as db:
        lesson = db.get(Lesson, args.lesson)
        if lesson is None or not lesson.transcript_json:
            raise SystemExit(f"lesson {args.lesson} not found or has no transcript (Anki lessons cannot be compared)")
        segs = db.exec(select(Segment).where(Segment.lesson_id == lesson.id).order_by(Segment.idx)).all()
    tr = Transcript.from_json(lesson.transcript_json)
    wav, sr = audio.read_wav(files.source_wav(lesson.id))
    total = len(wav) / sr
    device = settings.resolved_device()
    aligners = {"qwen3_fa": make_aligner("qwen3_fa", device), "mms_fa": make_aligner("mms_fa", device)}
    onsets: dict[str, list[float | None]] = {k: [] for k in ("asr", "qwen3_raw", "qwen3_repaired", "mms_fa")}
    spans: dict[str, list[list[Span]]] = {k: [] for k in ("qwen3_raw", "qwen3_repaired", "mms_fa")}
    truth: list[float | None] = []
    prev_end = 0.0
    for s in segs:
        if s.char_from is None or s.char_to is None:
            continue
        chars = tr.chars[s.char_from:s.char_to + 1]
        speech = [c for c in chars if not is_punct(c.c)]
        if not speech:
            continue
        c0, c1 = speech[0].start, speech[-1].end
        truth.append(energy_onset(wav, sr, max(prev_end, c0 - 0.5), c1))
        prev_end = c1
        onsets["asr"].append(c0)
        win = (max(0.0, c0 - MARGIN_S), min(total, c1 + MARGIN_S))
        coarse = coarse_times(s.text, chars)
        for name, aligner in aligners.items():
            try:
                got = align_in_window(aligner, wav, sr, s.text, *win)
            except Exception as e:  # noqa: BLE001  report and carry on
                print(f"sentence {s.idx}: {name} failed: {e}")
                got = []
            for key in (("qwen3_raw", "qwen3_repaired") if name == "qwen3_fa" else ("mms_fa",)):
                sp = repair_spans(got, coarse) if key == "qwen3_repaired" else got
                spans[key].append(sp)
                onsets[key].append(sp[0].start if sp else None)
    print(f"lesson {lesson.id} · {len(truth)} sentences · device {device}")
    print(f"{'source':16} {'n':>4} {'mean ms':>8} {'median':>8} {'<=100ms':>8} {'zero-len':>8}")
    results = {}
    for key, pred in onsets.items():
        e = onset_error(pred, truth)
        z = zero_length_share(spans[key]) if key in spans else 0.0
        results[key] = (e, z)
        print(f"{key:16} {e.n:>4} {e.mean_ms:>8} {e.median_ms:>8} {e.within_100ms:>8} {z:>8.3f}")
    print("verdict:", verdict(*results["qwen3_repaired"], *results["mms_fa"]))


if __name__ == "__main__":
    main()
```

Run: `cd backend && ~/.local/bin/uv run python scripts/compare_aligners.py --help`
Expected: a usage line `usage: compare_aligners.py [-h] --lesson LESSON` (no model is loaded).

Commit what exists so far:
```bash
git add backend/shadow/ingest/aligncheck.py backend/scripts/compare_aligners.py backend/tests/test_aligncheck.py
git commit -m "feat(backend): aligner comparison metrics and script"
```

- [ ] **Step 6: Controller runs the comparison and records the decision**

This step is run by the controller (needs the `models` extra, a GPU and the ~1.2 GB MMS_FA download), not by a subagent:
```bash
cd backend && ~/.local/bin/uv sync --extra dev --extra models && ~/.local/bin/uv run python scripts/compare_aligners.py --lesson 1
```
Copy the printed table and the verdict line into the **Ledger** at the bottom of this plan, with the date.

If the verdict is `qwen3_fa`: change nothing else; commit the ledger (`git add docs/superpowers/plans/2026-10-07-youtube-passages-guidance.md && git commit -m "docs(plan): record the aligner comparison"`).

If the verdict is `mms_fa`: make `auto` resolve to MMS_FA on every device. Append to `backend/tests/test_config.py`:
```python
def test_auto_aligner_is_mms_fa_on_every_device():
    from shadow.config import ModelsCfg, Settings
    for device in ("cuda", "cpu"):
        assert Settings(models=ModelsCfg(device=device)).resolved_aligner() == "mms_fa"
```
Run `cd backend && ~/.local/bin/uv run pytest tests/test_config.py -q` (expected FAIL: `'qwen3_fa' == 'mms_fa'`), then replace `resolved_aligner` in `backend/shadow/config.py` with:
```python
    def resolved_aligner(self) -> str:
        """`auto` is MMS_FA on every device: it beat Qwen3 on lesson 1 (plan 2026-10-07, ledger)."""
        if self.models.aligner != "auto":
            return self.models.aligner
        return "mms_fa"
```
In `config.toml` change the aligner comment to `# auto → mms_fa | qwen3_fa | mms_fa | mfa`; in `docs/running.md` replace "and Qwen3-ForcedAligner-0.6B (~2 GB, Hugging Face)" with "and the MMS_FA aligner (~1.2 GB, torchaudio)". Run `cd backend && ~/.local/bin/uv run pytest -q` (expected: all pass) and commit:
```bash
git add backend/shadow/config.py backend/tests/test_config.py config.toml docs/running.md docs/superpowers/plans/2026-10-07-youtube-passages-guidance.md
git commit -m "feat(backend): auto aligner resolves to MMS_FA (comparison in the plan ledger)"
```
Existing lessons improve only when re-ingested; say so to the user.

---

### Task 4: Frontend — a syllable click plays once

**Files:**
- Modify: `frontend/src/pages/Practice.tsx` (remove the loop; add `playSyllable`)
- Modify: `frontend/src/components/TwoTrack.tsx` (prop `onLoopSyllable` → `onPlaySyllable`)
- Modify: `frontend/src/pages/Practice.test.tsx` (TwoTrack mock; replace the `syllable loop` describe block)
- Modify: `docs/phase1-acceptance.md` (one line)

**Interfaces:**
- Consumes: `ClipPlayer.playRange(url, rate, fromS, toS, onTime?)` (existing).
- Produces: `TwoTrack` prop `onPlaySyllable: (i: number) => void` (replaces `onLoopSyllable`).

- [ ] **Step 1: Write the failing tests**

In `frontend/src/pages/Practice.test.tsx`, in the hoisted `h` object replace
```tsx
  twoTrack: null as null | { onLoopSyllable: (i: number) => void },
```
with
```tsx
  twoTrack: null as null | { onPlaySyllable: (i: number) => void },
```
and in the TwoTrack mock replace
```tsx
  default: (p: { onLoopSyllable: (i: number) => void }) => { h.twoTrack = p; return <div data-testid="two-track" /> },
```
with
```tsx
  default: (p: { onPlaySyllable: (i: number) => void }) => { h.twoTrack = p; return <div data-testid="two-track" /> },
```
Replace the whole `describe('syllable loop', () => { … })` block with:
```tsx
  describe('syllable click', () => {
    const aligned: LessonDetail = {
      ...lesson,
      segments: [{ ...seg(11, 0, '你好'), start_s: 10, end_s: 12, ref_alignment_json: [{ ch: '你', start: 10.2, end: 10.5, conf: 1 }, { ch: '好', start: 10.5, end: 11.25, conf: 1 }] }],
    }
    const sleep = (ms: number) => act(() => new Promise((r) => setTimeout(r, ms)))
    beforeEach(() => { h.api.lessons.get.mockResolvedValue(aligned) })

    it('plays the clip-relative span of the clicked syllable once', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      act(() => h.twoTrack!.onPlaySyllable(1))
      await flush()
      expect(h.player.playRange).toHaveBeenCalledTimes(1)
      const [url, rate, from, to] = h.player.playRange.mock.calls[0] as unknown as [string, number, number, number]
      expect([url, rate]).toEqual(['/seg/11.wav', 1])
      expect(from).toBeCloseTo(0.5, 5); expect(to).toBeCloseTo(1.25, 5)
      await sleep(600)
      expect(h.player.playRange).toHaveBeenCalledTimes(1) // no loop
    })

    it('clicking again plays it again; a click while recording does nothing', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      act(() => h.twoTrack!.onPlaySyllable(0)); await flush()
      act(() => h.twoTrack!.onPlaySyllable(0)); await flush()
      expect(h.player.playRange).toHaveBeenCalledTimes(2)
      press('Enter'); await flush()
      act(() => h.twoTrack!.onPlaySyllable(0)); await flush()
      expect(h.player.playRange).toHaveBeenCalledTimes(2)
    })
  })
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/Practice.test.tsx -t "syllable click"`
Expected: FAIL — `h.twoTrack!.onPlaySyllable is not a function`

- [ ] **Step 3: Implement**

`frontend/src/components/TwoTrack.tsx`: in `Props` replace `onPlayRef: () => void; onPlayYou: () => void; onLoopSyllable: (i: number) => void` with `onPlayRef: () => void; onPlayYou: () => void; onPlaySyllable: (i: number) => void`, and replace `<CellRow cells={cells} variant="ref" onCellClick={p.onLoopSyllable} />` with `<CellRow cells={cells} variant="ref" onCellClick={p.onPlaySyllable} />`.

`frontend/src/pages/Practice.tsx`:
- delete the line `const LOOP_GAP_MS = 250`;
- delete the line `const loopRef = useRef<{ cell: number; ctrl: AbortController } | null>(null) // a syllable loop in progress`;
- in `stopPlayback` delete the line `loopRef.current?.ctrl.abort(); loopRef.current = null`;
- replace the whole `loopSyllable` function (from its comment `// Loops one syllable of the reference until any other action; …` to its closing brace) with:
```tsx
  // Plays one syllable of the reference once (addendum §1.2); clicking again plays it again.
  // Alignment times are source-absolute, the clip starts at seg.start_s.
  function playSyllable(cell: number) {
    const ps = usePractice.getState(), s = currentSegment(ps), span = s?.ref_alignment_json?.[cell]
    if (!s || !span) return
    const url = api.segments.audioUrl(s.id, 'wav'), from = Math.max(0, span.start - s.start_s), to = Math.max(0, span.end - s.start_s)
    playSolo(() => player.playRange(url, ps.rate, from, to, setRefHead))
  }
```
- in the `<TwoTrack … />` element replace `onLoopSyllable={loopSyllable}` with `onPlaySyllable={playSyllable}`.

(`playSolo` already returns early while busy and stops other playback first.)

In `docs/phase1-acceptance.md` replace the line
`- [ ] Syllable cell click loops the right syllable (seek accuracy).`
with
`- [ ] Syllable cell click plays the right syllable once; clicking again plays it again (seek accuracy).`

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/Practice.test.tsx && npx eslint src`
Expected: PASS; eslint prints no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/Practice.tsx frontend/src/components/TwoTrack.tsx frontend/src/pages/Practice.test.tsx docs/phase1-acceptance.md
git commit -m "feat(frontend): a syllable click plays it once"
```

---
### Task 5: Backend — YouTube module (links, metadata, subtitle choice, errors, downloaders) and config

**Files:**
- Create: `backend/shadow/ingest/youtube.py`
- Test: `backend/tests/test_youtube.py`, `backend/tests/test_config.py` (append)
- Modify: `backend/pyproject.toml` and `backend/uv.lock` (via `uv add`), `backend/shadow/config.py` (`YoutubeCfg`), `config.toml` (`[youtube]`)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces (used by Tasks 6 and 9):
  - `parse_video_id(url: str) -> str | None`, `source_ref(video_id: str) -> str` (`"youtube::<id>"`), `watch_url(video_id: str) -> str`
  - `@dataclass VideoInfo(video_id: str, title: str, channel: str, upload_date: str | None = None, duration: float | None = None, chapters: list[dict] = [], subtitles: dict[str, list[str]] = {}, automatic_captions: dict[str, list[str]] = {}, is_live: bool = False)` — chapters are `{"title", "start_time", "end_time"}`; track dicts map language → available formats
  - `@dataclass(frozen=True) SubtitleChoice(lang: str, auto: bool, ext: str)`, `choose_subtitle(info: VideoInfo) -> SubtitleChoice | None`
  - `info_from_ytdlp(raw: dict) -> VideoInfo`, `readable_error(raw: str) -> str`, `class YoutubeError(RuntimeError)`
  - `class Downloader(Protocol)`: `probe(url) -> VideoInfo`, `download_audio(url, dest_dir: Path) -> Path`, `fetch_subtitle(url, choice: SubtitleChoice) -> str`
  - `YtDlpDownloader(cookies_file: str = "")`, `FakeDownloader(info: VideoInfo, audio: Path, subs: dict[tuple[str, bool], str] | None = None, error: Exception | None = None)` with `.fetched: list[tuple[str, bool]]`, `.downloads: int`, and `.error` raised by `probe`
  - `Settings.youtube`: `enabled: bool = True`, `max_minutes: int = 90`, `cookies_file: str = ""`

- [ ] **Step 1: Add yt-dlp and check its API**

Run: `cd backend && ~/.local/bin/uv add yt-dlp`
Expected: `pyproject.toml` gains `"yt-dlp>=<installed version>"` under `[project] dependencies` and `uv.lock` pins it.

Run:
```bash
cd backend && ~/.local/bin/uv run python -c "
import inspect, yt_dlp
from yt_dlp import YoutubeDL
doc = YoutubeDL.__doc__
print(yt_dlp.version.__version__)
print({k: k in doc for k in ['cookiefile', 'outtmpl', 'format', 'noplaylist', 'quiet', 'no_warnings', 'skip_download', 'noprogress']})
print(list(inspect.signature(YoutubeDL.extract_info).parameters)[:3], hasattr(YoutubeDL, 'urlopen'), hasattr(yt_dlp.utils, 'DownloadError'))
"
```
Expected: the version, every option `True`, `['self', 'url', 'download'] True True`. If an option prints `False`, find its current name in `YoutubeDL.__doc__` and use that name in `YtDlpDownloader._opts` / `download_audio` below.

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_youtube.py`:
```python
import pytest
from shadow.ingest.youtube import (SubtitleChoice, VideoInfo, YtDlpDownloader, choose_subtitle, info_from_ytdlp,
                                   parse_video_id, readable_error, source_ref, watch_url)

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize("url", [
    f"https://www.youtube.com/watch?v={VID}",
    f"https://youtube.com/watch?v={VID}&t=42s",
    f"https://m.youtube.com/watch?v={VID}&list=PL123&index=2",
    f"https://www.youtube.com/watch?feature=share&v={VID}",
    f"youtube.com/watch?v={VID}",
    f"https://youtu.be/{VID}",
    f"https://youtu.be/{VID}?si=abc&t=10",
    f"https://www.youtube.com/shorts/{VID}",
    f"https://youtube.com/shorts/{VID}?feature=share",
    f"  https://www.youtube.com/watch?v={VID}  ",
])
def test_parse_video_id_accepts_watch_short_and_shorts_links(url):
    assert parse_video_id(url) == VID


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/playlist?list=PL123", "https://vimeo.com/123", "https://www.youtube.com/watch?v=short",
    "https://youtu.be/", "not a url", "", f"https://evil.example/watch?v={VID}",
])
def test_parse_video_id_rejects_other_links(url):
    assert parse_video_id(url) is None


def test_refs():
    assert source_ref(VID) == f"youtube::{VID}"
    assert watch_url(VID) == f"https://www.youtube.com/watch?v={VID}"


def _info(manual=None, auto=None):
    return VideoInfo(video_id=VID, title="t", channel="c", subtitles=manual or {}, automatic_captions=auto or {})


@pytest.mark.parametrize("manual,auto,want", [
    ({"zh-Hans": ["vtt"], "zh-Hant": ["vtt"], "en": ["vtt"]}, {}, SubtitleChoice("zh-Hans", False, "vtt")),
    ({"zh-CN": ["vtt"]}, {}, SubtitleChoice("zh-CN", False, "vtt")),
    ({"zh-TW": ["vtt"], "en": ["vtt"]}, {"zh-Hans": ["vtt"]}, SubtitleChoice("zh-TW", False, "vtt")),
    ({"zh-Hant": ["srv3", "srt"]}, {}, SubtitleChoice("zh-Hant", False, "srt")),
    ({"zh": ["vtt"]}, {"zh-Hans": ["vtt"]}, SubtitleChoice("zh", False, "vtt")),
    ({"en": ["vtt"]}, {"zh-Hans": ["json3", "vtt"], "zh": ["vtt"]}, SubtitleChoice("zh-Hans", True, "vtt")),
    ({}, {"zh": ["vtt"], "en": ["vtt"]}, SubtitleChoice("zh", True, "vtt")),
    ({"en": ["vtt"], "ja": ["vtt"]}, {"en": ["vtt"]}, None),
    ({"zh-Hans": ["json3"]}, {}, None),
])
def test_choose_subtitle_prefers_manual_simplified_and_never_other_languages(manual, auto, want):
    assert choose_subtitle(_info(manual, auto)) == want


def test_info_from_ytdlp_maps_metadata_chapters_and_tracks():
    raw = {"id": VID, "title": "學中文", "uploader": "老師", "upload_date": "20260901", "duration": 754,
           "chapters": [{"title": "開始", "start_time": 0.0, "end_time": 300.0}, {"title": "x", "start_time": None}],
           "subtitles": {"zh-Hant": [{"ext": "vtt", "url": "u1"}, {"ext": "srv3", "url": "u2"}]},
           "automatic_captions": {"zh-Hans": [{"ext": "vtt", "url": "u3"}]}, "live_status": "not_live"}
    info = info_from_ytdlp(raw)
    assert (info.video_id, info.title, info.channel, info.upload_date, info.duration) == (VID, "學中文", "老師", "20260901", 754.0)
    assert info.chapters == [{"title": "開始", "start_time": 0.0, "end_time": 300.0}]
    assert info.subtitles == {"zh-Hant": ["vtt", "srv3"]} and info.automatic_captions == {"zh-Hans": ["vtt"]}
    assert info.is_live is False
    assert info_from_ytdlp({"id": VID, "channel": "频道", "uploader": "u"}).channel == "频道"
    assert info_from_ytdlp({"id": VID, "live_status": "is_live"}).is_live is True


@pytest.mark.parametrize("raw,want", [
    ("ERROR: [youtube] x: Private video. Sign in if you've been granted access to this video. Use --cookies-from-browser or --cookies for the authentication.", "private or unavailable"),
    ("ERROR: [youtube] x: Video unavailable. This video has been removed by the uploader", "private or unavailable"),
    ("ERROR: [youtube] x: Sign in to confirm your age. This video may be inappropriate for some users. Use --cookies", "this video needs a cookies file — see Settings"),
    ("ERROR: [youtube] x: Sign in to confirm you’re not a bot. Use --cookies-from-browser or --cookies", "this video needs a cookies file — see Settings"),
    ("ERROR: [youtube] x: Unable to download webpage: <urlopen error [Errno -3] Temporary failure in name resolution>", "network"),
    ("ERROR: [youtube] x: Unable to extract initial player response; please report this issue", "uv lock --upgrade-package yt-dlp"),
    ("ERROR: [youtube] x: nsig extraction failed: Some formats may be missing", "uv lock --upgrade-package yt-dlp"),
    ("ERROR: something new", "YouTube download failed: ERROR: something new"),
])
def test_readable_error(raw, want):
    assert want in readable_error(raw)


def test_ytdlp_options_carry_the_cookies_file_only_when_set(tmp_path):
    assert "cookiefile" not in YtDlpDownloader()._opts()
    opts = YtDlpDownloader(str(tmp_path / "c.txt"))._opts(skip_download=True)
    assert opts["cookiefile"] == str(tmp_path / "c.txt") and opts["skip_download"] is True and opts["noplaylist"] is True
```

Append to `backend/tests/test_config.py`:
```python
def test_youtube_defaults():
    from shadow.config import Settings
    y = Settings().youtube
    assert (y.enabled, y.max_minutes, y.cookies_file) == (True, 90, "")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_youtube.py tests/test_config.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'shadow.ingest.youtube'` (and `test_youtube_defaults` fails on `enabled False` / missing `max_minutes`).

- [ ] **Step 4: Write the module**

`backend/shadow/ingest/youtube.py`:
```python
"""YouTube lessons (addendum spec §2): link parsing, metadata, Chinese subtitle choice and audio download behind a
`Downloader` protocol (yt-dlp in production, `FakeDownloader` in tests), and error messages the user can act on."""
from __future__ import annotations
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qs, urlparse

_ID = re.compile(r"[A-Za-z0-9_-]{11}")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_SHORT_HOSTS = {"youtu.be", "www.youtu.be"}
# Manual tracks first, simplified before traditional (zh-CN / zh-HK are the regional names of the same scripts), then
# auto-generated ones. No other language is ever chosen, so none is ever downloaded.
MANUAL_LANGS = ("zh-Hans", "zh-CN", "zh-Hant", "zh-TW", "zh-HK", "zh")
AUTO_LANGS = ("zh-Hans", "zh")
SUBTITLE_EXTS = ("vtt", "srt")              # what parse_subtitles reads

COOKIES_HINT = "this video needs a cookies file — see Settings"
UPDATE_HINT = "update yt-dlp: `cd backend && uv lock --upgrade-package yt-dlp && uv sync --extra dev --extra models`"


class YoutubeError(RuntimeError):
    """A YouTube failure worded for the user; the lesson shows it as its error."""


def parse_video_id(url: str) -> str | None:
    """The 11-character id of a youtube.com/watch?v=…, youtu.be/… or youtube.com/shorts/… link, whatever else its
    query holds (&t=, &list=, ?si=); None for anything else."""
    s = url.strip()
    u = urlparse(s if "://" in s else f"https://{s}")
    host = (u.hostname or "").lower()
    parts = [p for p in u.path.split("/") if p]
    if host in _SHORT_HOSTS:
        cand = parts[0] if parts else ""
    elif host in _YOUTUBE_HOSTS and u.path == "/watch":
        cand = parse_qs(u.query).get("v", [""])[0]
    elif host in _YOUTUBE_HOSTS and len(parts) >= 2 and parts[0] in ("shorts", "live"):
        cand = parts[1]
    else:
        return None
    return cand if _ID.fullmatch(cand) else None


def source_ref(video_id: str) -> str:
    return f"youtube::{video_id}"


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


@dataclass
class VideoInfo:
    video_id: str
    title: str
    channel: str
    upload_date: str | None = None
    duration: float | None = None
    chapters: list[dict] = field(default_factory=list)                  # {"title", "start_time", "end_time"}
    subtitles: dict[str, list[str]] = field(default_factory=dict)       # manual tracks: language -> formats
    automatic_captions: dict[str, list[str]] = field(default_factory=dict)
    is_live: bool = False


@dataclass(frozen=True)
class SubtitleChoice:
    lang: str
    auto: bool
    ext: str


def choose_subtitle(info: VideoInfo) -> SubtitleChoice | None:
    """The Chinese track to use (see MANUAL_LANGS / AUTO_LANGS) in a format the subtitle parser reads, or None."""
    for tracks, langs, auto in ((info.subtitles, MANUAL_LANGS, False), (info.automatic_captions, AUTO_LANGS, True)):
        for lang in langs:
            ext = next((e for e in SUBTITLE_EXTS if e in tracks.get(lang, [])), None)
            if ext:
                return SubtitleChoice(lang, auto, ext)
    return None


def info_from_ytdlp(raw: dict[str, Any]) -> VideoInfo:
    """The fields shadow-speech uses from a yt-dlp info dict."""
    def tracks(d: dict | None) -> dict[str, list[str]]:
        return {lang: [t.get("ext", "") for t in ts or []] for lang, ts in (d or {}).items()}
    chapters = [{"title": c.get("title") or "", "start_time": float(c["start_time"]), "end_time": float(c["end_time"])}
                for c in raw.get("chapters") or []
                if c.get("start_time") is not None and c.get("end_time") is not None]
    return VideoInfo(
        video_id=raw.get("id", ""), title=raw.get("title") or raw.get("id", ""),
        channel=raw.get("channel") or raw.get("uploader") or "", upload_date=raw.get("upload_date"),
        duration=float(raw["duration"]) if raw.get("duration") else None, chapters=chapters,
        subtitles=tracks(raw.get("subtitles")), automatic_captions=tracks(raw.get("automatic_captions")),
        is_live=raw.get("live_status") == "is_live" or bool(raw.get("is_live")))


def readable_error(raw: str) -> str:
    """yt-dlp's error message reworded into what the user can do about it (checked in this order: yt-dlp appends
    "Use --cookies" to private-video errors too)."""
    m = raw.lower()
    if any(k in m for k in ("private video", "video unavailable", "this video is unavailable", "has been removed",
                            "members-only", "this video is not available")):
        return "YouTube: this video is private or unavailable"
    if any(k in m for k in ("sign in to confirm", "age-restricted", "inappropriate for some users", "--cookies")):
        return f"YouTube: {COOKIES_HINT}"
    if any(k in m for k in ("unable to download webpage", "urlopen error", "timed out", "name resolution",
                            "network is unreachable", "connection reset", "connection refused")):
        return "YouTube: could not reach YouTube (network error) — check the connection and try again"
    if any(k in m for k in ("unable to extract", "nsig", "signature", "please report this issue",
                            "requested format is not available", "only images are available")):
        return f"YouTube: extraction failed, yt-dlp is probably outdated — {UPDATE_HINT}"
    first = raw.strip().splitlines()[0] if raw.strip() else "unknown error"
    return f"YouTube download failed: {first}"


class Downloader(Protocol):
    def probe(self, url: str) -> VideoInfo: ...
    def download_audio(self, url: str, dest_dir: Path) -> Path: ...
    def fetch_subtitle(self, url: str, choice: SubtitleChoice) -> str: ...


class YtDlpDownloader:
    """yt-dlp's Python API. Only the chosen Chinese subtitle track is ever fetched."""

    def __init__(self, cookies_file: str = ""):
        self.cookies_file = cookies_file
        self._raw: dict[str, dict[str, Any]] = {}        # url -> info dict from probe(), for its subtitle URLs

    def _opts(self, **extra: Any) -> dict[str, Any]:
        opts: dict[str, Any] = {"quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True, **extra}
        if self.cookies_file:
            opts["cookiefile"] = str(Path(self.cookies_file).expanduser())
        return opts

    def probe(self, url: str) -> VideoInfo:
        import yt_dlp
        try:
            with yt_dlp.YoutubeDL(self._opts(skip_download=True)) as ydl:
                raw = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as e:
            raise YoutubeError(readable_error(str(e))) from e
        self._raw[url] = raw
        return info_from_ytdlp(raw)

    def download_audio(self, url: str, dest_dir: Path) -> Path:
        import yt_dlp
        dest_dir.mkdir(parents=True, exist_ok=True)
        opts = self._opts(format="bestaudio/best", outtmpl={"default": str(dest_dir / "audio.%(ext)s")})
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except yt_dlp.utils.DownloadError as e:
            raise YoutubeError(readable_error(str(e))) from e
        paths = [Path(d["filepath"]) for d in info.get("requested_downloads") or [] if d.get("filepath")]
        if not paths or not paths[0].exists():
            raise YoutubeError("YouTube download failed: yt-dlp wrote no audio file")
        return paths[0]

    def fetch_subtitle(self, url: str, choice: SubtitleChoice) -> str:
        import yt_dlp
        try:
            with yt_dlp.YoutubeDL(self._opts(skip_download=True)) as ydl:
                raw = self._raw.get(url) or ydl.extract_info(url, download=False)
                tracks = (raw.get("automatic_captions") if choice.auto else raw.get("subtitles")) or {}
                track = next((t for t in tracks.get(choice.lang, []) if t.get("ext") == choice.ext), None)
                if track is None:
                    raise YoutubeError(f"YouTube no longer offers the {choice.lang} subtitles")
                return ydl.urlopen(track["url"]).read().decode("utf-8-sig", errors="replace")
        except yt_dlp.utils.DownloadError as e:
            raise YoutubeError(readable_error(str(e))) from e


class FakeDownloader:
    """Tests: fixed metadata, `audio` copied as the download, subtitle text per (lang, auto). `error` is raised by
    probe(), where yt-dlp reports private, sign-in and network failures."""

    def __init__(self, info: VideoInfo, audio: Path, subs: dict[tuple[str, bool], str] | None = None,
                 error: Exception | None = None):
        self.info, self.audio, self.subs, self.error = info, audio, subs or {}, error
        self.fetched: list[tuple[str, bool]] = []
        self.downloads = 0

    def probe(self, url: str) -> VideoInfo:
        if self.error is not None:
            raise self.error
        return self.info

    def download_audio(self, url: str, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        self.downloads += 1
        dst = dest_dir / f"audio{self.audio.suffix}"
        shutil.copyfile(self.audio, dst)
        return dst

    def fetch_subtitle(self, url: str, choice: SubtitleChoice) -> str:
        self.fetched.append((choice.lang, choice.auto))
        if (choice.lang, choice.auto) not in self.subs:
            raise YoutubeError(f"YouTube no longer offers the {choice.lang} subtitles")
        return self.subs[(choice.lang, choice.auto)]
```

In `backend/shadow/config.py` replace `YoutubeCfg` with:
```python
class YoutubeCfg(BaseModel):
    enabled: bool = True
    max_minutes: int = 90
    cookies_file: str = ""
```

In `config.toml` replace the `[youtube]` table with:
```toml
[youtube]
enabled = true
max_minutes = 90                    # longer videos are refused
cookies_file = ""                   # Netscape cookies.txt for age/bot-checked videos (docs/running.md)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_youtube.py tests/test_config.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/shadow/ingest/youtube.py backend/tests/test_youtube.py backend/tests/test_config.py backend/shadow/config.py backend/pyproject.toml backend/uv.lock config.toml
git commit -m "feat(backend): YouTube links, metadata, subtitle choice and downloaders (yt-dlp)"
```

---

### Task 6: Backend — YouTube ingest and `POST /lessons/youtube`

**Files:**
- Modify: `backend/shadow/deps.py` (`Deps.downloader`, `build_deps`)
- Modify: `backend/shadow/ingest/pipeline.py` (new `ingest_youtube`)
- Modify: `backend/shadow/api/lessons.py` (extract `_delete_lesson`; new endpoint)
- Test: `backend/tests/test_youtube_api.py`

**Interfaces:**
- Consumes: Task 5 (`Downloader`, `YtDlpDownloader`, `YoutubeError`, `choose_subtitle`, `parse_video_id`, `source_ref`, `watch_url`); existing `ingest_upload(deps, engine, lesson_id, media_path, subtitle, progress)`, `_set_status`, `_merge_meta`, `to_simplified`.
- Produces:
  - `Deps.downloader: Downloader | None = None` (last field; `fake_deps` leaves it `None`, tests assign a `FakeDownloader`)
  - `ingest_youtube(deps: Deps, engine: Engine, lesson_id: int, url: str, progress: Progress) -> None`
  - `POST /lessons/youtube` body `{"url": str}` → `202 {"job_id": str, "lesson_id": int}`, or `200 {"job_id": null, "lesson_id": int}` for a video that already has a lesson not in `error`; `400` for a non-YouTube link or `[youtube] enabled = false`
  - `Lesson.meta_json` keys for YouTube lessons: `url`, `channel`, `upload_date`, `duration`, `chapters` (titles simplified), and `subtitle_track` when a Chinese track was used
  - `_delete_lesson(db: Session, files: FileLayout, lesson: Lesson) -> None` in `shadow.api.lessons` (Task 9 extends it)

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_youtube_api.py`:
```python
from sqlmodel import Session
from shadow.ingest.youtube import FakeDownloader, VideoInfo, YoutubeError, readable_error
from shadow.store.models import Lesson
from tests.conftest import LESSON_TEXT, wait_job
from tests.helpers import make_tone_wav

VID = "abcDEF12345"
URL = f"https://www.youtube.com/watch?v={VID}&t=42s"


def _vtt(cues):
    out = "WEBVTT\n\n"
    for a, b, t in cues:
        out += f"00:00:{a:06.3f} --> 00:00:{b:06.3f}\n{t}\n\n"
    return out


def _fake(client, tmp_path, manual=None, auto=None, subs=None, error=None, duration=8.0, chapters=None):
    info = VideoInfo(video_id=VID, title="學中文的方法", channel="老師頻道", upload_date="20260901", duration=duration,
                     chapters=chapters or [], subtitles=manual or {}, automatic_captions=auto or {})
    fake = FakeDownloader(info, make_tone_wav(tmp_path / "yt.wav", 8.0), subs, error)
    client.app.state.deps.downloader = fake
    return fake


def _lesson(client, lid):
    with Session(client.app.state.engine) as db:
        return db.get(Lesson, lid)


def test_youtube_lesson_takes_text_from_chinese_subtitles(client, tmp_path):
    fake = _fake(client, tmp_path, manual={"zh-Hant": ["vtt"], "en": ["vtt"]},
                 subs={("zh-Hant", False): _vtt(LESSON_TEXT)})
    r = client.post("/lessons/youtube", json={"url": URL})
    assert r.status_code == 202
    assert wait_job(client, r.json()["job_id"])["status"] == "done"
    lesson = _lesson(client, r.json()["lesson_id"])
    assert (lesson.status, lesson.source_type, lesson.source_ref) == ("ready", "youtube", f"youtube::{VID}")
    assert (lesson.title, lesson.speaker) == ("学中文的方法", "老师频道")
    meta = lesson.meta_json
    assert meta["url"] == f"https://www.youtube.com/watch?v={VID}" and meta["channel"] == "老師頻道"
    assert (meta["upload_date"], meta["duration"], meta["chapters"]) == ("20260901", 8.0, [])
    assert meta["subtitle_track"] == "zh-Hant" and meta["subtitle_match"] == 1.0
    assert fake.fetched == [("zh-Hant", False)]                        # English is never fetched
    segs = client.get(f"/lessons/{lesson.id}").json()["segments"]
    assert [s["text"] for s in segs] == [t for _, _, t in LESSON_TEXT]


def test_youtube_lesson_without_chinese_subtitles_uses_the_asr_text(client, tmp_path):
    fake = _fake(client, tmp_path, manual={"en": ["vtt"]})
    r = client.post("/lessons/youtube", json={"url": f"https://youtu.be/{VID}"}).json()
    wait_job(client, r["job_id"])
    lesson = _lesson(client, r["lesson_id"])
    assert lesson.status == "ready" and fake.fetched == []
    assert "subtitle_track" not in lesson.meta_json and "subtitle_match" not in lesson.meta_json


def test_an_unreadable_subtitle_track_falls_back_to_the_asr(client, tmp_path):
    fake = _fake(client, tmp_path, auto={"zh-Hans": ["vtt"]})            # listed, but fetching it fails
    r = client.post("/lessons/youtube", json={"url": URL}).json()
    wait_job(client, r["job_id"])
    lesson = _lesson(client, r["lesson_id"])
    assert lesson.status == "ready" and fake.fetched == [("zh-Hans", True)]
    assert "zh-Hans" in lesson.meta_json["subtitle_ignored"]


def test_adding_the_same_video_again_returns_its_lesson_without_a_job(client, tmp_path):
    fake = _fake(client, tmp_path)
    first = client.post("/lessons/youtube", json={"url": URL}).json()
    wait_job(client, first["job_id"])
    again = client.post("/lessons/youtube", json={"url": f"https://m.youtube.com/watch?v={VID}&list=PL1&index=2"})
    assert again.status_code == 200 and again.json() == {"job_id": None, "lesson_id": first["lesson_id"]}
    assert fake.downloads == 1 and len(client.get("/lessons").json()) == 1


def test_a_failed_video_is_reingested_when_added_again(client, tmp_path):
    fake = _fake(client, tmp_path, error=YoutubeError(readable_error("Sign in to confirm your age. Use --cookies")))
    first = client.post("/lessons/youtube", json={"url": URL}).json()
    assert wait_job(client, first["job_id"])["status"] == "error"
    lesson = _lesson(client, first["lesson_id"])
    assert (lesson.status, lesson.error) == ("error", "YouTube: this video needs a cookies file — see Settings")
    fake.error = None
    second = client.post("/lessons/youtube", json={"url": URL})
    assert second.status_code == 202 and second.json()["job_id"]
    assert wait_job(client, second.json()["job_id"])["status"] == "done"
    assert client.get(f"/lessons/{first['lesson_id']}").status_code == 404
    assert [l["status"] for l in client.get("/lessons").json()] == ["ready"]


def test_a_video_over_the_length_limit_is_refused_readably(client, tmp_path):
    fake = _fake(client, tmp_path, duration=91 * 60)
    r = client.post("/lessons/youtube", json={"url": URL}).json()
    assert wait_job(client, r["job_id"])["status"] == "error"
    error = _lesson(client, r["lesson_id"]).error
    assert "91 min" in error and "max_minutes" in error and fake.downloads == 0


def test_bad_links_and_disabled_youtube_are_400(client):
    assert client.post("/lessons/youtube", json={"url": "https://vimeo.com/1"}).status_code == 400
    client.app.state.settings.youtube.enabled = False
    r = client.post("/lessons/youtube", json={"url": URL})
    assert r.status_code == 400 and "enabled" in r.json()["detail"]


def test_ingest_youtube_reports_the_download_stage_first(data_dir, fake_transcript, tmp_path):
    from shadow.ingest.pipeline import ingest_youtube
    from tests.test_pipeline import _setup
    deps, engine, lid = _setup(data_dir, fake_transcript)
    deps.downloader = FakeDownloader(VideoInfo(video_id=VID, title="t", channel="c"), make_tone_wav(tmp_path / "a.wav", 8.0))
    stages = []
    ingest_youtube(deps, engine, lid, URL, lambda s, f: stages.append(s))
    assert list(dict.fromkeys(stages))[:3] == ["download", "normalise", "transcribe"] and stages[-1] == "done"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_youtube_api.py -q`
Expected: FAIL — `POST /lessons/youtube` returns 404/405 and `ingest_youtube` cannot be imported.

- [ ] **Step 3: Give `Deps` a downloader**

In `backend/shadow/deps.py` add `from shadow.ingest.youtube import Downloader, YtDlpDownloader`, add the last field of `Deps`:
```python
    downloader: Downloader | None = None       # YouTube (addendum §2); None in fake_deps until a test sets one
```
and in `build_deps` pass `downloader=YtDlpDownloader(settings.youtube.cookies_file)` to `Deps(...)`.

- [ ] **Step 4: Write `ingest_youtube`**

In `backend/shadow/ingest/pipeline.py` change the text import to `from shadow.ingest.text import is_punct, parse_subtitles, strip_punct, to_simplified`, add `from shadow.ingest.youtube import YoutubeError, choose_subtitle, watch_url`, and append:
```python
def ingest_youtube(deps: Deps, engine: Engine, lesson_id: int, url: str, progress: Progress) -> None:
    """Addendum §2: the video's metadata, its Chinese subtitles (if any) and its best audio stream, then the upload
    pipeline (subtitle text, ASR timing). The lesson takes the video's title and channel (simplified) and keeps url,
    channel, upload_date, duration and chapters in meta_json. On failure the lesson is `error` with a readable
    message and the exception is re-raised."""
    try:
        _set_status(engine, lesson_id, "processing")
        progress("download", 0.0)
        if deps.downloader is None:
            raise RuntimeError("YouTube downloads are not set up on this server")
        info = deps.downloader.probe(url)
        if info.is_live:
            raise YoutubeError("YouTube: live streams cannot be added; add the video once the stream has ended")
        limit = deps.settings.youtube.max_minutes
        if info.duration and info.duration > limit * 60:
            raise YoutubeError(f"YouTube: this video is {round(info.duration / 60)} min long; the limit is {limit} min "
                               "([youtube] max_minutes in config.toml)")
        _set_status(engine, lesson_id, "processing", title=to_simplified(info.title) or info.video_id,
                    speaker=to_simplified(info.channel))
        _merge_meta(engine, lesson_id, url=watch_url(info.video_id), channel=info.channel,
                    upload_date=info.upload_date, duration=info.duration,
                    chapters=[{**c, "title": to_simplified(c["title"])} for c in info.chapters])
        progress("download", 0.1)
        subtitle = None
        choice = choose_subtitle(info)
        if choice is not None:
            try:
                subtitle = (f"youtube.{choice.lang}.{choice.ext}", deps.downloader.fetch_subtitle(url, choice))
                _merge_meta(engine, lesson_id, subtitle_track=choice.lang + (" (auto)" if choice.auto else ""))
            except Exception as e:  # noqa: BLE001  subtitles are optional: the ASR text is used instead
                log.warning("could not fetch the %s subtitles; using the ASR transcript", choice.lang, exc_info=True)
                _merge_meta(engine, lesson_id, subtitle_ignored=f"could not download the {choice.lang} subtitles: {e}")
        progress("download", 0.2)
        media = deps.downloader.download_audio(url, deps.files.lesson_dir(lesson_id) / "download")
        progress("download", 1.0)
    except Exception as e:  # noqa: BLE001
        _set_status(engine, lesson_id, "error", error=str(e) or type(e).__name__)
        raise
    ingest_upload(deps, engine, lesson_id, media, subtitle, progress)
```

- [ ] **Step 5: Add the endpoint and extract the delete**

In `backend/shadow/api/lessons.py`:
- change the fastapi import to `from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile`;
- change the pipeline import to `from shadow.ingest.pipeline import ingest_upload, ingest_youtube`;
- add `from shadow.ingest.youtube import parse_video_id, source_ref, watch_url` and `from shadow.store.files import FileLayout`;
- replace the body of `delete_lesson` (everything after its docstring) with:
```python
    _delete_lesson(db, request.app.state.files, _get_lesson(db, lesson_id))
```
- add above `delete_lesson`:
```python
def _delete_lesson(db: Session, files: FileLayout, lesson: Lesson) -> None:
    """Delete the lesson, its segments, their attempts and scores, its sessions and its files."""
    lesson_id = lesson.id
    segs = db.exec(select(Segment).where(Segment.lesson_id == lesson_id)).all()
    attempt_files: list[Path] = []
    if segs:
        seg_ids = [s.id for s in segs]
        for sc in db.exec(select(SyllableScore).where(SyllableScore.segment_id.in_(seg_ids))).all():
            db.delete(sc)
        for a in db.exec(select(Attempt).where(Attempt.segment_id.in_(seg_ids))).all():
            if a.audio_path:
                attempt_files.append(Path(a.audio_path))
            db.delete(a)
        db.flush()
    for ps in db.exec(select(PracticeSession).where(PracticeSession.lesson_id == lesson_id)).all():
        db.delete(ps)
    db.flush()
    for s in segs:
        db.delete(s)
    db.delete(lesson); db.commit()
    for f in attempt_files:
        f.unlink(missing_ok=True)
    shutil.rmtree(files.lesson_dir(lesson_id), ignore_errors=True)
```
- add after `create_lesson`:
```python
class YoutubeIn(BaseModel):
    url: str


@router.post("/lessons/youtube", status_code=202)
def add_youtube(body: YoutubeIn, request: Request, response: Response, db: Session = Depends(get_session)):
    """Addendum §2: one lesson per video (`source_ref` youtube::<id>). A video that already has a lesson returns it
    with no job, unless that lesson failed: then it is deleted and the video ingested again."""
    deps, engine, jobs = request.app.state.deps, request.app.state.engine, request.app.state.jobs
    if not request.app.state.settings.youtube.enabled:
        raise HTTPException(400, "YouTube lessons are off: set [youtube] enabled = true in config.toml")
    vid = parse_video_id(body.url)
    if vid is None:
        raise HTTPException(400, "not a YouTube video link (youtube.com/watch?v=…, youtu.be/…, youtube.com/shorts/…)")
    ref = source_ref(vid)
    existing = db.exec(select(Lesson).where(Lesson.source_type == "youtube", Lesson.source_ref == ref)).first()
    if existing is not None and existing.status != "error":
        response.status_code = 200
        return {"job_id": None, "lesson_id": existing.id}
    if existing is not None:
        _delete_lesson(db, request.app.state.files, existing)
    lesson = Lesson(title=vid, speaker="", source_type="youtube", source_ref=ref)
    db.add(lesson); db.commit(); db.refresh(lesson)
    lesson_id, url = lesson.id, watch_url(vid)
    job_id = jobs.submit(lambda progress: ingest_youtube(deps, engine, lesson_id, url, progress), lesson_id)
    return {"job_id": job_id, "lesson_id": lesson_id}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_youtube_api.py tests/test_lessons_api.py -q`
Expected: PASS

Run: `cd backend && ~/.local/bin/uv run pytest -q`
Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add backend/shadow/deps.py backend/shadow/ingest/pipeline.py backend/shadow/api/lessons.py backend/tests/test_youtube_api.py
git commit -m "feat(backend): YouTube lessons via POST /lessons/youtube"
```

---

### Task 7: Frontend — YouTube hand-off (paste box, `?add=`, bookmarklet) and the running docs

**Files:**
- Create: `frontend/src/lib/handoff.ts`, `frontend/src/lib/handoff.test.ts`, `frontend/src/pages/Settings.test.tsx`
- Modify: `frontend/src/api/client.ts`, `frontend/src/pages/Library.tsx`, `frontend/src/pages/Library.test.tsx`, `frontend/src/pages/Settings.tsx`
- Modify: `docs/running.md` (YouTube section)

**Interfaces:**
- Consumes: `POST /lessons/youtube` (Task 6).
- Produces: `api.lessons.youtube(url: string): Promise<{ job_id: string | null; lesson_id: number }>`; `bookmarkletCode(origin: string): string`; `addQuestion(url: string, title?: string | null): string`.

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/handoff.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import { addQuestion, bookmarkletCode } from './handoff'

describe('hand-off', () => {
  it('builds the bookmarklet for the app origin', () => {
    expect(bookmarkletCode('http://127.0.0.1:5173')).toBe("javascript:location.href='http://127.0.0.1:5173/library?add='+encodeURIComponent(location.href)")
  })
  it('asks with the title when there is one, else the link', () => {
    expect(addQuestion('https://youtu.be/x', null)).toBe('Add https://youtu.be/x to shadow-speech?')
    expect(addQuestion('https://youtu.be/x', ' 学中文 ')).toBe('Add 学中文 to shadow-speech?')
  })
})
```

`frontend/src/pages/Settings.test.tsx`:
```tsx
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import Settings from './Settings'

describe('<Settings> YouTube', () => {
  afterEach(cleanup)
  it('offers the bookmarklet for this origin', () => {
    render(<Settings />)
    const link = screen.getByRole('link', { name: '→ shadow-speech' })
    expect(link.getAttribute('href')).toBe(`javascript:location.href='${window.location.origin}/library?add='+encodeURIComponent(location.href)`)
  })
})
```

In `frontend/src/pages/Library.test.tsx`:
- change the imports to
```tsx
import { StrictMode } from 'react'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
```
- change the hoisted mock to
```tsx
const h = vi.hoisted(() => ({
  api: { lessons: { list: vi.fn(), remove: vi.fn(), patch: vi.fn(), youtube: vi.fn() }, jobs: { events: vi.fn() } },
}))
```
- append:
```tsx
describe('Library YouTube hand-off', () => {
  beforeEach(() => {
    h.api.lessons.list.mockReset().mockResolvedValue([lesson(1)])
    h.api.lessons.youtube.mockReset().mockResolvedValue({ job_id: 'j1', lesson_id: 2 })
    h.api.jobs.events.mockReset().mockReturnValue(() => {})
  })
  afterEach(() => { cleanup(); vi.restoreAllMocks() })
  function Where() { const l = useLocation(); return <div data-testid="where">{l.pathname + l.search}</div> }
  // StrictMode runs effects twice: the ?add= question must still come once.
  const open = (entry: string) => render(
    <StrictMode><MemoryRouter initialEntries={[entry]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes><Route path="/library" element={<><Library /><Where /></>} /></Routes>
    </MemoryRouter></StrictMode>)
  const paste = async (url: string) => {
    const box = await screen.findByLabelText('Paste a YouTube link')
    fireEvent.change(box, { target: { value: url } })
    fireEvent.keyDown(box, { key: 'Enter' })
  }

  it('a pasted link is added on Enter and its job is watched', async () => {
    open('/library')
    await paste(' https://youtu.be/abcDEF12345 ')
    await waitFor(() => expect(h.api.lessons.youtube).toHaveBeenCalledWith('https://youtu.be/abcDEF12345'))
    await waitFor(() => expect(h.api.jobs.events).toHaveBeenCalledWith('j1', expect.any(Function), expect.any(Function)))
  })

  it('a video already in the library says so and starts no job', async () => {
    h.api.lessons.youtube.mockResolvedValue({ job_id: null, lesson_id: 1 })
    open('/library')
    await paste('https://youtu.be/abcDEF12345')
    expect(await screen.findByText('That video is already in the library.')).toBeInTheDocument()
    expect(h.api.jobs.events).not.toHaveBeenCalled()
  })

  it('?add= asks once, adds on yes and clears the parameter', async () => {
    const ask = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const url = 'https://www.youtube.com/watch?v=abcDEF12345&t=3'
    open('/library?add=' + encodeURIComponent(url))
    await waitFor(() => expect(h.api.lessons.youtube).toHaveBeenCalledWith(url))
    expect(h.api.lessons.youtube).toHaveBeenCalledTimes(1)
    expect(ask).toHaveBeenCalledTimes(1)
    expect(ask).toHaveBeenCalledWith(`Add ${url} to shadow-speech?`)
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/library$/))
  })

  it('declining ?add= adds nothing but still clears the parameter', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    open('/library?add=https%3A%2F%2Fyoutu.be%2FabcDEF12345')
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/library$/))
    expect(h.api.lessons.youtube).not.toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/lib/handoff.test.ts src/pages/Library.test.tsx src/pages/Settings.test.tsx`
Expected: FAIL — `./handoff` cannot be resolved; no "Paste a YouTube link" field; no bookmarklet link.

- [ ] **Step 3: Implement**

`frontend/src/lib/handoff.ts`:
```ts
// The Brave bookmarklet (addendum §3): opens this app's library with the page the user is on, which asks before adding it.
export function bookmarkletCode(origin: string): string {
  return `javascript:location.href='${origin}/library?add='+encodeURIComponent(location.href)`
}

// The question asked when the library opens with ?add=<url> (an optional &title= is shown instead of the link).
export function addQuestion(url: string, title?: string | null): string {
  return `Add ${title?.trim() || url} to shadow-speech?`
}
```

`frontend/src/api/client.ts`, in `lessons` after `ankiImport`:
```ts
    youtube: (url: string) => req<{ job_id: string | null; lesson_id: number }>('/lessons/youtube', json('POST', { url })),
```

`frontend/src/pages/Library.tsx`:
- imports: `import { Link, useNavigate, useSearchParams } from 'react-router-dom'`, `import { api, ApiError } from '../api/client'`, `import { addQuestion } from '../lib/handoff'`;
- in `readable` add as its first line: `if (e instanceof ApiError) return e.detail`;
- after `const closers = useRef<(() => void)[]>([])` add:
```tsx
  const [link, setLink] = useState('')
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const addHandled = useRef(false)      // StrictMode runs effects twice; the ?add= question comes once
```
- after `watch` add:
```tsx
  async function addYoutube(url: string) {
    const u = url.trim()
    if (!u) return
    try {
      const r = await api.lessons.youtube(u)
      setLink('')
      await reload()
      if (r.job_id) { watch(r.job_id, r.lesson_id); setMsg('Adding the video: downloading…') }
      else setMsg('That video is already in the library.')
    } catch (e) { setMsg(`Could not add the video: ${readable(e, BACKEND_HINT)}`) }
  }
  // The bookmarklet opens /library?add=<url>: ask once, take the parameter out of the address bar, add on yes.
  useEffect(() => {
    const url = params.get('add')
    if (url == null || addHandled.current) return
    addHandled.current = true
    const title = params.get('title')
    navigate('/library', { replace: true })
    if (window.confirm(addQuestion(url, title))) void addYoutube(url)
  }, [params]) // eslint-disable-line react-hooks/exhaustive-deps -- only a new ?add= matters
```
- in the drop-zone row, between the `<label …>` and the Anki buttons, add:
```tsx
          <input className="inp w-72" placeholder="Paste a YouTube link" aria-label="Paste a YouTube link" value={link}
            onChange={(e) => setLink(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void addYoutube(link) } }} />
```

`frontend/src/pages/Settings.tsx`:
- imports: `import { Fragment, useEffect, useRef, useState } from 'react'` and `import { bookmarkletCode } from '../lib/handoff'`;
- after the existing state hooks add:
```tsx
  const bookmarklet = useRef<HTMLAnchorElement>(null)
  // Set outside JSX: React warns about javascript: URLs in href props.
  useEffect(() => { bookmarklet.current?.setAttribute('href', bookmarkletCode(window.location.origin)) }, [])
```
- add a section after the Practice section:
```tsx
      <section className="space-y-2">
        <h2 className="text-fghi">YouTube</h2>
        <p className="text-sm text-fgdim">Drag this link to the Brave bookmarks bar. On a YouTube video, click it to send the video here.</p>
        <a ref={bookmarklet} className="btn inline-block" onClick={(e) => e.preventDefault()}>→ shadow-speech</a>
        <p className="text-sm text-fgdim">Videos behind an age or "not a bot" check need your YouTube cookies: export them to a
          cookies.txt file and set <code>[youtube] cookies_file</code> in config.toml (see docs/running.md, YouTube).</p>
      </section>
```

Append to `docs/running.md`:
```markdown
## YouTube
YouTube lessons are on by default (`[youtube] enabled = true`). Paste a link into the Library's "Paste a YouTube link"
field, or drag the "→ shadow-speech" bookmarklet from Settings to the Brave bookmarks bar and click it on a video page.
Videos longer than `[youtube] max_minutes` (default 90) are refused. Chinese subtitles are used when the video has
them (manual first, then auto-generated); otherwise the ASR text is used.

Cookies: age-restricted videos and YouTube's "confirm you're not a bot" check need your browser's YouTube cookies.
While signed in to YouTube, export them with a cookies.txt browser extension (Netscape format), save the file
somewhere private (e.g. `~/shadow-cookies.txt`), set `[youtube] cookies_file = "/home/<you>/shadow-cookies.txt"` in
config.toml and restart the backend. Cookies expire; export them again when the error comes back.

Deno: recent yt-dlp versions need a JavaScript runtime for YouTube. If a download fails mentioning a JS runtime or
Deno, install it (`curl -fsSL https://deno.land/install.sh | sh`) and make sure `deno` is on the PATH of the shell that
runs `make dev`.

Updating yt-dlp: YouTube changes often. When a lesson fails with "extraction failed, yt-dlp is probably outdated":

    cd backend && uv lock --upgrade-package yt-dlp && uv sync --extra dev --extra models
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/lib/handoff.test.ts src/pages/Library.test.tsx src/pages/Settings.test.tsx && npx eslint src`
Expected: PASS; no eslint errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/handoff.ts frontend/src/lib/handoff.test.ts frontend/src/api/client.ts frontend/src/pages/Library.tsx frontend/src/pages/Library.test.tsx frontend/src/pages/Settings.tsx frontend/src/pages/Settings.test.tsx docs/running.md
git commit -m "feat(frontend): add YouTube videos by link, bookmarklet and ?add="
```

---

### Task 8: Backend — `Passage` table and the passage planner

**Files:**
- Modify: `backend/shadow/store/models.py` (new `Passage`)
- Create: `backend/shadow/ingest/passages.py`
- Test: `backend/tests/test_passages.py`; `backend/tests/test_lessons_api.py` (autoincrement table list)

**Interfaces:**
- Consumes: `Lesson`, `Segment` models; `Lesson.meta_json["chapters"]` (Task 6 writes it for YouTube lessons).
- Produces (used by Task 9):
  - `class Passage(SQLModel, table=True)`: `id, lesson_id, idx, title: str, start_s: float, end_s: float`
  - `@dataclass PassagePlan(start_s: float, end_s: float, title: str | None = None)`
  - `@dataclass PassageView(idx: int, title: str, start_s: float, end_s: float, segment_ids: list[int], done: bool)`
  - `plan_passages(segs: list[tuple[float, float]], chapters: list[dict] | None = None) -> list[PassagePlan]`
  - `default_title(i: int, start_s: float, end_s: float) -> str` → `"Passage {i+1} · mm:ss–mm:ss"`
  - `plan_for(lesson: Lesson, segs: list[Segment]) -> list[PassagePlan]` (titles filled)
  - `rebuild_passages(engine: Engine, lesson_id: int) -> None`
  - `passage_index(starts: list[float], seg_start: float) -> int`
  - `passage_views(plans: list[PassagePlan], segs: list[tuple[int, float, int]]) -> list[PassageView]` — `segs` are `(segment id, start_s, attempts)` in lesson order

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_passages.py`:
```python
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
```

In `backend/tests/test_lessons_api.py`, in `test_every_table_with_deletable_rows_uses_autoincrement`, change the table tuple to `("lesson", "segment", "attempt", "session", "syllablescore", "passage")`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_passages.py tests/test_lessons_api.py -q`
Expected: FAIL — `ImportError` for `Passage` / `shadow.ingest.passages`; `KeyError: 'passage'` in the autoincrement test.

- [ ] **Step 3: Add the table**

Append to `backend/shadow/store/models.py`:
```python
class Passage(SQLModel, table=True):
    """A contiguous run of segments of about 2–3 minutes (addendum §4). Only the time range is stored: a segment
    belongs to the passage whose range contains its start_s."""
    __table_args__ = {"sqlite_autoincrement": True}   # ids never reused after a delete (clip URLs, prefs, exports)
    id: int | None = Field(default=None, primary_key=True)
    lesson_id: int = Field(foreign_key="lesson.id", index=True)
    idx: int
    title: str
    start_s: float
    end_s: float
```
(`init_db` creates the new table on existing databases; no migration is needed.)

- [ ] **Step 4: Write the planner**

`backend/shadow/ingest/passages.py`:
```python
"""Passages (addendum spec §4): contiguous runs of segments of about 2–3 minutes, the unit of Flow runs and progress.

Boundaries come from the video's chapters when it has them (a chapter longer than SPLIT_CHAPTER_OVER_S is split like
a lesson); otherwise from a greedy cut: from a passage's first segment, cut before the segment starting CUT_WINDOW
after it with the longest pause before it (ties: the cut nearest TARGET_S), never leaving a last passage shorter than
MIN_LAST_S. A lesson shorter than ONE_PASSAGE_UNDER_S is one passage, chapters or not. Rows store only the time
range; a segment belongs to the last passage starting at or before its start_s (the first when it starts before them
all), so edits never break the mapping."""
from __future__ import annotations
from bisect import bisect_right
from dataclasses import dataclass, field
from sqlalchemy import Engine
from sqlmodel import Session, select
from shadow.store.models import Lesson, Passage, Segment

TARGET_S = 150.0
CUT_WINDOW = (120.0, 180.0)
MIN_LAST_S = 60.0
ONE_PASSAGE_UNDER_S = 240.0
SPLIT_CHAPTER_OVER_S = 240.0

Bounds = tuple[float, float]


@dataclass
class PassagePlan:
    start_s: float
    end_s: float
    title: str | None = None          # None: default_title()


@dataclass
class PassageView:
    idx: int
    title: str
    start_s: float
    end_s: float
    segment_ids: list[int] = field(default_factory=list)
    done: bool = False


def _mmss(t: float) -> str:
    t = max(0, int(t))
    return f"{t // 60:02d}:{t % 60:02d}"


def default_title(i: int, start_s: float, end_s: float) -> str:
    return f"Passage {i + 1} · {_mmss(start_s)}–{_mmss(end_s)}"


def _greedy(segs: list[Bounds]) -> list[list[int]]:
    """Indices of `segs` (ordered by start) per passage."""
    groups: list[list[int]] = []
    a, n, end = 0, len(segs), max(b for _, b in segs)
    lo, hi = CUT_WINDOW
    while a < n:
        t0 = segs[a][0]
        if a == 0 and end - t0 < ONE_PASSAGE_UNDER_S:
            cut = n
        else:
            fits = [k for k in range(a + 1, n) if lo <= segs[k][0] - t0 <= hi and end - segs[k][0] >= MIN_LAST_S]
            if fits:
                cut = max(fits, key=lambda k: (round(segs[k][0] - segs[k - 1][1], 3), -abs(segs[k][0] - t0 - TARGET_S)))
            elif end - t0 <= hi + MIN_LAST_S:
                cut = n                   # the rest is one passage; a short remainder is absorbed
            else:
                later = [k for k in range(a + 1, n) if segs[k][0] - t0 > hi and end - segs[k][0] >= MIN_LAST_S]
                cut = later[0] if later else n
        groups.append(list(range(a, cut)))
        a = cut
    return groups


def plan_passages(segs: list[Bounds], chapters: list[dict] | None = None) -> list[PassagePlan]:
    """Passages over `segs` ((start_s, end_s), ordered by start); titles only from chapters."""
    if not segs:
        return []
    end = max(b for _, b in segs)
    if end - segs[0][0] < ONE_PASSAGE_UNDER_S:
        return [PassagePlan(segs[0][0], end)]
    if not chapters:
        return [PassagePlan(segs[g[0]][0], max(segs[k][1] for k in g)) for g in _greedy(segs)]
    plans: list[PassagePlan] = []
    chs = sorted(chapters, key=lambda c: c["start_time"])
    for n, ch in enumerate(chs):
        lo = ch["start_time"] if n else float("-inf")           # speech before the first chapter joins it
        hi = chs[n + 1]["start_time"] if n + 1 < len(chs) else float("inf")
        mine = [s for s in segs if lo <= s[0] < hi]
        if not mine:
            continue
        title = ch.get("title") or None
        if ch["end_time"] - ch["start_time"] > SPLIT_CHAPTER_OVER_S:
            groups = _greedy(mine)
            for m, g in enumerate(groups):
                plans.append(PassagePlan(mine[g[0]][0], max(mine[k][1] for k in g),
                                         f"{title} ({m + 1}/{len(groups)})" if title else None))
        else:
            plans.append(PassagePlan(mine[0][0], max(b for _, b in mine), title))
    return plans


def plan_for(lesson: Lesson, segs: list[Segment]) -> list[PassagePlan]:
    """The lesson's passages from its segments (and YouTube chapters), every title filled in."""
    bounds = sorted((s.start_s, s.end_s) for s in segs)
    plans = plan_passages(bounds, (lesson.meta_json or {}).get("chapters"))
    return [PassagePlan(p.start_s, p.end_s, p.title or default_title(i, p.start_s, p.end_s)) for i, p in enumerate(plans)]


def rebuild_passages(engine: Engine, lesson_id: int) -> None:
    """Replace the lesson's Passage rows with a fresh plan (after ingest, resplit and merge); no-op for a deleted lesson."""
    with Session(engine) as db:
        lesson = db.get(Lesson, lesson_id)
        if lesson is None:
            return
        segs = db.exec(select(Segment).where(Segment.lesson_id == lesson_id)).all()
        for row in db.exec(select(Passage).where(Passage.lesson_id == lesson_id)).all():
            db.delete(row)
        for i, p in enumerate(plan_for(lesson, segs)):
            db.add(Passage(lesson_id=lesson_id, idx=i, title=p.title, start_s=p.start_s, end_s=p.end_s))
        db.commit()


def passage_index(starts: list[float], seg_start: float) -> int:
    """Index of the passage (by ascending `starts`) a segment starting at `seg_start` belongs to."""
    return max(bisect_right(starts, seg_start) - 1, 0)


def passage_views(plans: list[PassagePlan], segs: list[tuple[int, float, int]]) -> list[PassageView]:
    """`plans` (ordered by start) with their members: `segs` are (segment id, start_s, attempts) in lesson order. A
    passage is done when it has segments and every one has an attempt."""
    if not plans:
        return []
    starts = [p.start_s for p in plans]
    views = [PassageView(i, p.title or default_title(i, p.start_s, p.end_s), p.start_s, p.end_s, [], True)
             for i, p in enumerate(plans)]
    for sid, start, attempts in segs:
        v = views[passage_index(starts, start)]
        v.segment_ids.append(sid)
        v.done = v.done and attempts > 0
    for v in views:
        v.done = v.done and bool(v.segment_ids)
    return views
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_passages.py tests/test_lessons_api.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/shadow/store/models.py backend/shadow/ingest/passages.py backend/tests/test_passages.py backend/tests/test_lessons_api.py
git commit -m "feat(backend): passage table and planner"
```

---

### Task 9: Backend — passages built on ingest and edits, listed by the API

**Files:**
- Modify: `backend/shadow/schemas.py` (`PassageOut`; `LessonOut`, `LessonDetail` fields)
- Modify: `backend/shadow/ingest/pipeline.py` (`ingest_upload`), `backend/shadow/ingest/anki.py` (`ingest_anki_group`)
- Modify: `backend/shadow/api/segments.py` (`resplit`, `merge_next`), `backend/shadow/api/lessons.py` (`_lesson_out`, `get_lesson`, `_delete_lesson`)
- Test: `backend/tests/test_passages_api.py`

**Interfaces:**
- Consumes: Task 8 (`Passage`, `PassagePlan`, `plan_for`, `passage_views`, `rebuild_passages`).
- Produces:
  - `PassageOut {idx, title, start_s, end_s, segment_ids: list[int], done: bool}`
  - `GET /lessons/{id}` adds `passages: PassageOut[]`; `GET /lessons` (and `PATCH /lessons/{id}`) add `passage_count: int`, `passages_done: int`
  - a lesson with segments but no Passage rows (created before this change) gets passages computed on the fly (not stored)

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_passages_api.py`:
```python
from sqlmodel import Session, select
from shadow.store.models import Attempt, Passage
from tests.conftest import wait_job
from tests.test_lessons_api import _upload


def test_lesson_detail_lists_passages_with_members_and_done(client, tmp_path):
    lid = _upload(client, tmp_path)
    detail = client.get(f"/lessons/{lid}").json()
    ids, end = [s["id"] for s in detail["segments"]], detail["segments"][-1]["end_s"]
    assert detail["passages"] == [{"idx": 0, "title": f"Passage 1 · 00:00–00:{int(end):02d}", "start_s": 0.0,
                                   "end_s": end, "segment_ids": ids, "done": False}]
    tile = client.get("/lessons").json()[0]
    assert (tile["passage_count"], tile["passages_done"]) == (1, 0)
    with Session(client.app.state.engine) as db:
        for sid in ids:
            db.add(Attempt(segment_id=sid, mode="flow", audio_path="x.wav", duration_s=1.0))
        db.commit()
    assert client.get(f"/lessons/{lid}").json()["passages"][0]["done"] is True
    assert client.get("/lessons").json()[0]["passages_done"] == 1


def test_resplit_and_merge_rebuild_passages(client, tmp_path, monkeypatch):
    import shadow.api.segments as segments_api
    calls, real = [], segments_api.rebuild_passages
    monkeypatch.setattr(segments_api, "rebuild_passages", lambda engine, lid: (calls.append(lid), real(engine, lid)))
    lid = _upload(client, tmp_path)
    seg = client.get(f"/lessons/{lid}").json()["segments"][0]
    assert client.post(f"/segments/{seg['id']}/resplit", json={"at_char_index": 7}).status_code == 200
    detail = client.get(f"/lessons/{lid}").json()
    assert len(detail["segments"]) == 4
    assert detail["passages"][0]["segment_ids"] == [s["id"] for s in detail["segments"]]
    assert client.post(f"/segments/{seg['id']}/merge-next").status_code == 200
    detail = client.get(f"/lessons/{lid}").json()
    assert detail["passages"][0]["segment_ids"] == [s["id"] for s in detail["segments"]]
    assert calls == [lid, lid]


def test_lesson_without_passage_rows_gets_computed_passages(client, tmp_path):
    lid = _upload(client, tmp_path)
    with Session(client.app.state.engine) as db:               # as if ingested before passages existed
        for p in db.exec(select(Passage).where(Passage.lesson_id == lid)).all():
            db.delete(p)
        db.commit()
    detail = client.get(f"/lessons/{lid}").json()
    assert len(detail["passages"]) == 1
    assert detail["passages"][0]["segment_ids"] == [s["id"] for s in detail["segments"]]
    assert client.get("/lessons").json()[0]["passage_count"] == 1


def test_anki_import_builds_passages(client, tmp_path):
    from tests.test_anki_import import _b64, _dict
    b64 = _b64(tmp_path, seconds=2.0)
    notes = [_dict(1, "你好世界。", "v.mp4 00:00:01.000", b64), _dict(2, "再见。", "v.mp4 00:00:05.000", b64)]
    job = client.post("/lessons/anki", json={"query_name": "q", "notes": notes}).json()["jobs"][0]
    assert wait_job(client, job["job_id"])["status"] == "done"
    with Session(client.app.state.engine) as db:
        rows = db.exec(select(Passage).where(Passage.lesson_id == job["lesson_id"])).all()
    assert len(rows) == 1 and rows[0].title.startswith("Passage 1 · 00:00–")


def test_deleting_a_lesson_deletes_its_passages(client, tmp_path):
    lid = _upload(client, tmp_path)
    assert client.delete(f"/lessons/{lid}").status_code == 204
    with Session(client.app.state.engine) as db:
        assert db.exec(select(Passage).where(Passage.lesson_id == lid)).all() == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_passages_api.py -q`
Expected: FAIL — `KeyError: 'passages'` / `'passage_count'`; no Passage rows after ingest.

- [ ] **Step 3: Schemas**

In `backend/shadow/schemas.py` add before `LessonOut`:
```python
class PassageOut(BaseModel):
    idx: int
    title: str
    start_s: float
    end_s: float
    segment_ids: list[int]
    done: bool
```
add to `LessonOut` after `mean_last_score`:
```python
    passage_count: int = 0
    passages_done: int = 0
```
and replace `LessonDetail` with:
```python
class LessonDetail(LessonOut):
    segments: list[SegmentOut]
    passages: list[PassageOut] = []
```

- [ ] **Step 4: Build passages on ingest and edits**

- `backend/shadow/ingest/pipeline.py`: add `from shadow.ingest.passages import rebuild_passages`; in `ingest_upload` replace
```python
        build_segments(deps, engine, lesson_id, source_wav, tr, sentences, progress)
        _set_status(engine, lesson_id, "ready", duration_s=duration, transcript_json=tr.to_json())
```
with
```python
        build_segments(deps, engine, lesson_id, source_wav, tr, sentences, progress)
        rebuild_passages(engine, lesson_id)
        _set_status(engine, lesson_id, "ready", duration_s=duration, transcript_json=tr.to_json())
```
- `backend/shadow/ingest/anki.py`: add `from shadow.ingest.passages import rebuild_passages`; in `ingest_anki_group`, right after the `build_segments(...)` call inside `if sentences:`, add `rebuild_passages(engine, lesson_id)` (same indentation as the call).
- `backend/shadow/api/segments.py`: add `from shadow.ingest.passages import rebuild_passages`; at the end of `resplit` replace its last two lines (`renumber(…)` and `return [_fresh_out(…), _fresh_out(…)]`) with
```python
    renumber(deps, engine, lesson_id)
    rebuild_passages(engine, lesson_id)
    return [_fresh_out(db, left_id), _fresh_out(db, right_id)]
```
and at the end of `merge_next` replace its last two lines (`renumber(…)` and `return _fresh_out(db, sid)`) with
```python
    renumber(deps, engine, lesson_id)
    rebuild_passages(engine, lesson_id)
    return _fresh_out(db, sid)
```

- [ ] **Step 5: List passages in the lessons API**

In `backend/shadow/api/lessons.py`:
- imports: `from dataclasses import asdict`, `from shadow.ingest.passages import PassagePlan, passage_views, plan_for`, change the schemas import to `from shadow.schemas import LessonDetail, LessonOut, PassageOut, SegmentOut`, and add `Passage` to the models import;
- in `_delete_lesson`, before `for s in segs:` add:
```python
    for p in db.exec(select(Passage).where(Passage.lesson_id == lesson_id)).all():
        db.delete(p)
```
- replace `_lesson_out` and `get_lesson` with:
```python
def _passages(db: Session, lesson: Lesson, segs: list[Segment], outs: list[SegmentOut]) -> list[PassageOut]:
    """Stored passages, or for a lesson ingested before passages existed a plan computed now (not stored)."""
    if not segs:
        return []
    rows = db.exec(select(Passage).where(Passage.lesson_id == lesson.id).order_by(Passage.idx)).all()
    plans = [PassagePlan(r.start_s, r.end_s, r.title) for r in rows] or plan_for(lesson, segs)
    views = passage_views(plans, [(o.id, o.start_s, o.attempts) for o in outs])
    return [PassageOut(**asdict(v)) for v in views]


def _lesson_parts(db: Session, lesson: Lesson) -> tuple[list[SegmentOut], list[PassageOut]]:
    segs = db.exec(select(Segment).where(Segment.lesson_id == lesson.id).order_by(Segment.idx)).all()
    outs = [_segment_out(db, s) for s in segs]
    return outs, _passages(db, lesson, segs, outs)


def _lesson_out(db: Session, lesson: Lesson, parts: tuple[list[SegmentOut], list[PassageOut]] | None = None) -> LessonOut:
    outs, passages = parts or _lesson_parts(db, lesson)
    last = [o.last_score for o in outs if o.last_score is not None]
    return LessonOut(**lesson.model_dump(exclude={"meta_json", "transcript_json"}), segment_count=len(outs),
                     practised_count=sum(1 for o in outs if o.attempts),
                     mean_last_score=sum(last) / len(last) if last else None,
                     passage_count=len(passages), passages_done=sum(1 for p in passages if p.done))
```
and
```python
@router.get("/lessons/{lesson_id}", response_model=LessonDetail)
def get_lesson(lesson_id: int, db: Session = Depends(get_session)):
    lesson = _get_lesson(db, lesson_id)
    parts = _lesson_parts(db, lesson)
    return LessonDetail(**_lesson_out(db, lesson, parts).model_dump(), segments=parts[0], passages=parts[1])
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_passages_api.py -q && ~/.local/bin/uv run pytest -q`
Expected: PASS; the whole suite passes.

- [ ] **Step 7: Commit**

```bash
git add backend/shadow/schemas.py backend/shadow/ingest/pipeline.py backend/shadow/ingest/anki.py backend/shadow/api/segments.py backend/shadow/api/lessons.py backend/tests/test_passages_api.py
git commit -m "feat(backend): build passages on ingest and edits; list them in the lessons API"
```

---
### Task 10: Frontend — passages in Practice, the drawer and the library

**Files:**
- Create: `frontend/src/lib/passages.ts`, `frontend/src/lib/passages.test.ts`, `frontend/src/components/Drawer.test.tsx`
- Modify: `frontend/src/api/types.ts`, `frontend/src/store/practice.ts`, `frontend/src/components/Drawer.tsx`, `frontend/src/components/TopBar.tsx`, `frontend/src/pages/Practice.tsx`, `frontend/src/pages/useFlow.ts`, `frontend/src/pages/Library.tsx`
- Test: `frontend/src/pages/Practice.test.tsx`, `frontend/src/pages/Library.test.tsx`

**Interfaces:**
- Consumes: `GET /lessons/{id}` `passages`, `GET /lessons` `passage_count` / `passages_done` (Task 9).
- Produces:
  - types: `Passage { idx; title; start_s; end_s; segment_ids: number[]; done: boolean }`; `Lesson.passage_count?: number`, `Lesson.passages_done?: number`; `LessonDetail.passages?: Passage[]`
  - store: `PracticeState.practised: number[]` (sentence ids with an attempt uploaded during this visit; reset by `setLesson`), `markPractised(id: number): void`, `replaceSegments(segs: Segment[], passages?: Passage[]): void`
  - `passageIndexOf(passages: Passage[], segments: Segment[], i: number): number`, `passageSpan(p: Passage, segments: Segment[]): { from: number; to: number } | null`, `passageDone(p: Passage, segments: Segment[], practised: readonly number[]): boolean`, `groupByPassage(segments: Segment[], passages: Passage[]): { passage: Passage | null; rows: { i: number; seg: Segment }[] }[]`
  - `TopBar` prop `passage?: PassagePick | null` with `export interface PassagePick { index: number; titles: string[]; onPick: (k: number) => void }`
  - `Drawer` props `passages?: Passage[]`, `practised?: readonly number[]`

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/passages.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import type { Passage, Segment } from '../api/types'
import { groupByPassage, passageDone, passageIndexOf, passageSpan } from './passages'

const seg = (id: number, attempts = 0): Segment => ({
  id, lesson_id: 1, idx: id, start_s: id, end_s: id + 1, text: 't', translation: null, words_json: null, ref_alignment_json: null,
  difficulty_flag: false, anki_note_id: null, last_score: null, best_score: null, attempts,
})
const p = (idx: number, ids: number[]): Passage => ({ idx, title: `P${idx + 1}`, start_s: 0, end_s: 1, segment_ids: ids, done: false })
const segments = [seg(10, 1), seg(11), seg(12), seg(13)]
const passages = [p(0, [10, 11]), p(1, [12, 13])]

describe('passages', () => {
  it('finds the passage of a sentence and its sentence range', () => {
    expect([0, 1, 2, 3, 9].map((i) => passageIndexOf(passages, segments, i))).toEqual([0, 0, 1, 1, -1])
    expect(passageSpan(passages[1], segments)).toEqual({ from: 2, to: 3 })
    expect(passageSpan(p(2, [99]), segments)).toBeNull()
  })
  it('is done when every sentence has an attempt, on the server or in this session', () => {
    expect(passageDone(passages[0], segments, [])).toBe(false)
    expect(passageDone(passages[0], segments, [11])).toBe(true)
    expect(passageDone(p(2, []), segments, [])).toBe(false)
  })
  it('groups the drawer by passage; sentences no passage lists come last', () => {
    const g = groupByPassage([...segments, seg(14)], passages)
    expect(g.map((x) => [x.passage?.title ?? null, x.rows.map((r) => r.i)])).toEqual([['P1', [0, 1]], ['P2', [2, 3]], [null, [4]]])
    expect(groupByPassage(segments, []).map((x) => x.passage)).toEqual([null])
  })
})
```

`frontend/src/components/Drawer.test.tsx`:
```tsx
import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Passage, Segment } from '../api/types'
import Drawer from './Drawer'

const seg = (id: number, attempts = 0): Segment => ({
  id, lesson_id: 1, idx: id - 10, start_s: 0, end_s: 1, text: `句子${id}`, translation: null, words_json: null, ref_alignment_json: null,
  difficulty_flag: false, anki_note_id: null, last_score: null, best_score: null, attempts,
})
const passages: Passage[] = [
  { idx: 0, title: 'P1', start_s: 0, end_s: 1, segment_ids: [10, 11], done: false },
  { idx: 1, title: 'P2', start_s: 1, end_s: 2, segment_ids: [12], done: false },
]
const noop = () => {}

describe('<Drawer> passages', () => {
  it('groups sentences under passage headers with a ✓ once the passage is done', () => {
    render(<Drawer segments={[seg(10, 1), seg(11), seg(12)]} idx={0} open pendingIds={new Set()} passages={passages} practised={[11]}
      onJump={noop} onToggle={noop} onEdit={noop} onSplit={noop} onMerge={noop} />)
    expect(screen.getAllByTestId('passage-header').map((h) => h.textContent)).toEqual(['P1✓', 'P2'])
    expect(within(screen.getByTestId('passage-0')).getAllByRole('button', { name: /^Actions for sentence/ })).toHaveLength(2)
  })
})
```

In `frontend/src/pages/Practice.test.tsx`, append inside `describe('<Practice>', …)` (top level):
```tsx
  describe('passages', () => {
    const twoPassages: LessonDetail = { ...lesson, passages: [
      { idx: 0, title: 'Passage 1 · 00:00–00:02', start_s: 0, end_s: 2, segment_ids: [11], done: false },
      { idx: 1, title: 'Passage 2 · 00:02–00:04', start_s: 2, end_s: 4, segment_ids: [12], done: false }] }
    beforeEach(() => { h.api.lessons.get.mockResolvedValue(twoPassages) })

    it('the top bar shows the passage and jumps to another one', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      expect(screen.getByText(/Passage 1 \/ 2/)).toBeInTheDocument()
      fireEvent.change(screen.getByLabelText('Go to passage'), { target: { value: '1' } })
      expect(await screen.findByText('再见', { selector: 'p.sentence' })).toBeInTheDocument()
      expect(screen.getByText(/Passage 2 \/ 2/)).toBeInTheDocument()
    })
  })
```
and inside `describe('Flow', …)`:
```tsx
    it('the range defaults to the current passage', async () => {
      h.api.lessons.get.mockResolvedValue({ ...lesson, passages: [
        { idx: 0, title: 'P1', start_s: 0, end_s: 2, segment_ids: [11], done: false },
        { idx: 1, title: 'P2', start_s: 2, end_s: 4, segment_ids: [12], done: false }] })
      clipsTake(2)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('along')
      expect(await screen.findByText(/Flow finished · 1 sentences/)).toBeInTheDocument()
      expect(h.player.play.mock.calls.map((c) => (c as unknown[])[0])).toEqual(['/seg/11.opus'])
    })
```

In `frontend/src/pages/Library.test.tsx`, inside `describe('Library tile actions', …)`:
```tsx
  it('a tile shows passage progress', async () => {
    await show([lesson(1, { passage_count: 2, passages_done: 1 })])
    expect(screen.getByText(/1 \/ 2 passages/)).toBeInTheDocument()
  })
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/lib/passages.test.ts src/components/Drawer.test.tsx src/pages/Practice.test.tsx src/pages/Library.test.tsx`
Expected: FAIL — `./passages` cannot be resolved; no passage headers / selector / tile text; Flow plays both clips.

- [ ] **Step 3: Types, store and helpers**

`frontend/src/api/types.ts`: add
```ts
export interface Passage { idx: number; title: string; start_s: number; end_s: number; segment_ids: number[]; done: boolean }
```
add `passage_count?: number; passages_done?: number` to `Lesson` (after `mean_last_score`), and replace `export interface LessonDetail extends Lesson { segments: Segment[] }` with
```ts
export interface LessonDetail extends Lesson { segments: Segment[]; passages?: Passage[] }
```

`frontend/src/store/practice.ts`:
- import `Passage` too: `import type { LessonDetail, Mode, Passage, Segment } from '../api/types'`;
- in `PracticeState` add `practised: number[]` (after `hint: string`) and the methods `markPractised: (id: number) => void`; change `replaceSegments: (segs: Segment[]) => void` to `replaceSegments: (segs: Segment[], passages?: Passage[]) => void`;
- initial state: add `practised: []`;
- `setLesson`: return `{ lesson, idx: 0, attemptsThisSegment: 0, lastAttempt: null, hint: '', practised: [] }`;
- add `markPractised: (id) => set((s) => (s.practised.includes(id) ? {} : { practised: [...s.practised, id] })),`
- replace `replaceSegments` with
```ts
  replaceSegments: (segments, passages) => set((s) => (s.lesson ? { lesson: { ...s.lesson, segments, ...(passages ? { passages } : {}) } } : {})),
```

`frontend/src/lib/passages.ts`:
```ts
import type { Passage, Segment } from '../api/types'

// Passages (addendum §4): the server lists each passage's sentence ids; these helpers place sentences in them.

// The position in `passages` of the passage holding the sentence at lesson index `i`, or -1.
export function passageIndexOf(passages: Passage[], segments: Segment[], i: number): number {
  const id = segments[i]?.id
  return id == null ? -1 : passages.findIndex((p) => p.segment_ids.includes(id))
}

// First and last lesson index of the passage's sentences, or null when none of them is in `segments`.
export function passageSpan(p: Passage, segments: Segment[]): { from: number; to: number } | null {
  const idx = segments.map((s, i) => (p.segment_ids.includes(s.id) ? i : -1)).filter((i) => i >= 0)
  return idx.length ? { from: idx[0], to: idx[idx.length - 1] } : null
}

// Done: every sentence has at least one attempt, on the server or uploaded during this visit.
export function passageDone(p: Passage, segments: Segment[], practised: readonly number[]): boolean {
  const byId = new Map(segments.map((s) => [s.id, s]))
  return p.segment_ids.length > 0 && p.segment_ids.every((id) => (byId.get(id)?.attempts ?? 0) > 0 || practised.includes(id))
}

// The drawer's groups: each passage with its sentences (lesson index and sentence) in lesson order; sentences no passage
// lists (only between an edit and the next reload) go in a last group without a passage.
export function groupByPassage(segments: Segment[], passages: Passage[]): { passage: Passage | null; rows: { i: number; seg: Segment }[] }[] {
  if (!passages.length) return [{ passage: null, rows: segments.map((seg, i) => ({ i, seg })) }]
  const owner = new Map<number, number>()
  passages.forEach((p, k) => p.segment_ids.forEach((id) => owner.set(id, k)))
  const groups = passages.map((passage) => ({ passage: passage as Passage | null, rows: [] as { i: number; seg: Segment }[] }))
  const loose: { i: number; seg: Segment }[] = []
  segments.forEach((seg, i) => { const k = owner.get(seg.id); if (k == null) loose.push({ i, seg }); else groups[k].rows.push({ i, seg }) })
  return loose.length ? [...groups, { passage: null, rows: loose }] : groups
}
```

- [ ] **Step 4: Drawer, top bar and library tile**

Replace `frontend/src/components/Drawer.tsx` with:
```tsx
import { useState } from 'react'
import type { Passage, Segment } from '../api/types'
import { groupByPassage, passageDone } from '../lib/passages'
export function dotClass(seg: Segment, pending: boolean): string {
  if (pending) return 'border border-dashed border-fgdim'
  if (seg.last_score == null) return 'bg-line'
  return seg.last_score >= 0.8 ? 'bg-ok' : seg.last_score >= 0.6 ? 'bg-warn' : 'bg-bad'
}
interface Props {
  segments: Segment[]; idx: number; open: boolean; pendingIds: Set<number>; onJump: (i: number) => void; onToggle: () => void
  onEdit: (i: number) => void; onSplit: (i: number) => void; onMerge: (i: number) => void
  passages?: Passage[]; practised?: readonly number[]
}
// The lesson's sentences, grouped under passage headers (✓ when every sentence of the passage has an attempt).
export default function Drawer({ segments, idx, open, pendingIds, onJump, onToggle, onEdit, onSplit, onMerge, passages = [], practised = [] }: Props) {
  const [menu, setMenu] = useState<number | null>(null) // the row whose ⋯ menu is open
  if (!open) return <button className="w-6 border-l border-line text-fgdim text-xs" onClick={onToggle} title="Open lesson list (L)">▸</button>
  const pick = (fn: (i: number) => void, i: number) => () => { setMenu(null); fn(i) }
  const item = 'px-2 py-0.5 rounded bg-panel2 hover:text-fghi disabled:opacity-40'
  return (
    <aside className="w-80 border-l border-line overflow-y-auto">
      <div className="flex justify-between px-3 py-2 text-[10px] uppercase tracking-widest text-fgdim"><span>Lesson</span><button onClick={onToggle}>◂ L</button></div>
      {groupByPassage(segments, passages).map((g, gi) => (
        <div key={g.passage ? `p${g.passage.idx}` : `loose${gi}`} data-testid={g.passage ? `passage-${g.passage.idx}` : 'passage-none'}>
          {g.passage && (
            <div data-testid="passage-header" className="flex justify-between gap-2 px-3 pt-3 pb-1 text-[10px] uppercase tracking-widest text-fgdim">
              <span className="truncate">{g.passage.title}</span>
              {passageDone(g.passage, segments, practised) && <span className="text-ok" aria-label="passage done">✓</span>}
            </div>)}
          {g.rows.map(({ i, seg: s }) => (
            <div key={s.id}>
              <div className={`flex items-center text-sm ${i === idx ? 'bg-[#1c2a3a] text-fghi' : 'text-fgdim'}`}>
                <button onClick={() => onJump(i)} title={`${s.text}${s.last_score != null ? `\nlast ${Math.round(s.last_score * 100)} · best ${Math.round((s.best_score ?? 0) * 100)}` : ''}`}
                  className="flex-1 min-w-0 flex items-center gap-2 pl-3 py-1 text-left">
                  <span className="w-5 text-right text-[10px]">{s.idx + 1}</span>
                  <span className={`w-2 h-2 rounded-full flex-none ${dotClass(s, pendingIds.has(s.id))}`} />
                  <span className="truncate font-hanzi">{s.text}</span>
                  {s.difficulty_flag && <span className="text-warn">⚑</span>}
                </button>
                <button className="px-2 py-1 text-fgdim hover:text-fghi" aria-label={`Actions for sentence ${i + 1}`} aria-haspopup="menu" aria-expanded={menu === i}
                  onClick={() => setMenu(menu === i ? null : i)}>⋯</button>
              </div>
              {menu === i && (
                <div role="menu" className="flex gap-1 px-3 py-1 text-xs text-fgdim">
                  <button role="menuitem" className={item} onClick={pick(onEdit, i)}>Edit text</button>
                  <button role="menuitem" className={item} onClick={pick(onSplit, i)}>Split here</button>
                  <button role="menuitem" className={item} onClick={pick(onMerge, i)} disabled={i === segments.length - 1}>Merge with next</button>
                </div>)}
            </div>))}
        </div>))}
    </aside>
  )
}
```

Replace `frontend/src/components/TopBar.tsx` with:
```tsx
import { Link } from 'react-router-dom'
import type { Mode } from '../api/types'

export interface PassagePick { index: number; titles: string[]; onPick: (k: number) => void }
interface Props {
  title: string; speaker: string; idx: number; total: number; mode: Mode; onMode: (m: Mode) => void; elapsedS: number
  passage?: PassagePick | null
}
export default function TopBar({ title, speaker, idx, total, mode, onMode, elapsedS, passage }: Props) {
  const mm = String(Math.floor(elapsedS / 60)).padStart(2, '0'), ss = String(Math.floor(elapsedS % 60)).padStart(2, '0')
  return (
    <div className="flex items-center justify-between px-4 py-2 border-b border-line text-sm text-fgdim">
      <span><Link to="/library" className="mr-3 hover:text-fghi" title="Back to the library">←</Link>
        <span className="font-hanzi text-fghi">{speaker && `${speaker} · `}{title}</span> &nbsp; {idx + 1} / {total}
        {passage && passage.titles.length > 0 && (
          <label className="ml-3">Passage {Math.max(0, passage.index) + 1} / {passage.titles.length}
            <select aria-label="Go to passage" className="ml-1 bg-panel2 rounded px-1 py-0.5 text-fg" value={Math.max(0, passage.index)}
              onChange={(e) => passage.onPick(Number(e.target.value))}>
              {passage.titles.map((t, k) => <option key={k} value={k}>{t}</option>)}
            </select></label>)}</span>
      <span className="flex gap-1">{(['echo', 'chorus', 'flow', 'guided'] as Mode[]).map((m) => (
        <button key={m} onClick={() => onMode(m)} className={`px-2 py-0.5 rounded border ${m === mode ? 'bg-[#1c2a3a] border-accent text-white' : 'border-line'}`}>{m[0].toUpperCase() + m.slice(1)}</button>))}</span>
      <span className={elapsedS >= 1200 ? 'text-warn' : ''} title="Session time">⏱ {mm}:{ss}</span>
    </div>
  )
}
```

`frontend/src/pages/Library.tsx`: in the tile's stats template replace
```tsx
                        : `${l.segment_count} sentences · ${l.practised_count} practised${l.mean_last_score != null ? ` · mean ${Math.round(l.mean_last_score * 100)}` : ''}`}
```
with
```tsx
                        : `${l.segment_count} sentences · ${l.practised_count} practised${l.mean_last_score != null ? ` · mean ${Math.round(l.mean_last_score * 100)}` : ''}${l.passage_count ? ` · ${l.passages_done ?? 0} / ${l.passage_count} passages` : ''}`}
```

- [ ] **Step 5: Practice and Flow**

`frontend/src/pages/Practice.tsx`:
- add `import { passageIndexOf, passageSpan } from '../lib/passages'`;
- in `finishRecording` replace
```tsx
      api.segments.postAttempt(s.id, wav, { session_id: ps.sessionId ?? undefined, mode }).catch((e) => setError(`Upload failed: ${message(e)}`))
```
with
```tsx
      api.segments.postAttempt(s.id, wav, { session_id: ps.sessionId ?? undefined, mode })
        .then(() => usePractice.getState().markPractised(s.id)).catch((e) => setError(`Upload failed: ${message(e)}`))
```
and replace
```tsx
      .then((a) => { const cur = usePractice.getState(); if (cur.lastAttempt?.url === url) cur.setLastAttempt({ ...take, id: a.id }) })
```
with
```tsx
      .then((a) => { const cur = usePractice.getState(); cur.markPractised(s.id); if (cur.lastAttempt?.url === url) cur.setLastAttempt({ ...take, id: a.id }) })
```
- replace `flowRange` with:
```tsx
  // Flow: the setup form's range, defaulting to the current sentence's passage (addendum §4), or to the current
  // sentence through the last when the lesson has no passages.
  function flowRange() {
    const ps = usePractice.getState(), segs = ps.lesson?.segments ?? [], last = Math.max(0, segs.length - 1)
    const clamp = (i: number) => Math.max(0, Math.min(last, i))
    const passages = ps.lesson?.passages ?? []
    const k = passageIndexOf(passages, segs, ps.idx)
    const span = k >= 0 ? passageSpan(passages[k], segs) : null
    const from = clamp(flow.state.from ?? span?.from ?? ps.idx), to = clamp(flow.state.to ?? span?.to ?? last)
    return { from: Math.min(from, to), to: Math.max(from, to) }
  }
  // The top bar's passage selector: to the passage's first sentence (Flow's range follows it). Not during a Flow run.
  function pickPassage(k: number) {
    const l = usePractice.getState().lesson, p = l?.passages?.[k]
    const span = l && p ? passageSpan(p, l.segments) : null
    if (!span || runRef.current?.kind === 'flow') return
    flow.setForm({ from: null, to: null })
    goTo(span.from)
  }
```
- in `changeSegments` replace `ps.replaceSegments(l.segments)` with `ps.replaceSegments(l.segments, l.passages)`;
- after `const segments = st.lesson.segments` add `const passages = st.lesson.passages ?? []`;
- in the `<TopBar … />` element add the prop
```tsx
        passage={passages.length ? { index: passageIndexOf(passages, segments, flowRunning ? fs.current : st.idx), titles: passages.map((p) => p.title), onPick: pickPassage } : null}
```
- in the `<Drawer … />` element add `passages={passages} practised={st.practised}`.

`frontend/src/pages/useFlow.ts`:
- replace `      try { attemptId = (await api.segments.postAttempt(t.rg.segmentId, t.wav, { session_id, mode: 'flow' })).id }` with
```ts
      try {
        attemptId = (await api.segments.postAttempt(t.rg.segmentId, t.wav, { session_id, mode: 'flow' })).id
        usePractice.getState().markPractised(t.rg.segmentId)
      }
```
- replace `ps.replaceSegments(l.segments)` with `ps.replaceSegments(l.segments, l.passages)`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run && npx eslint src`
Expected: PASS; no eslint errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/store/practice.ts frontend/src/lib/passages.ts frontend/src/lib/passages.test.ts frontend/src/components/Drawer.tsx frontend/src/components/Drawer.test.tsx frontend/src/components/TopBar.tsx frontend/src/pages/Practice.tsx frontend/src/pages/Practice.test.tsx frontend/src/pages/useFlow.ts frontend/src/pages/Library.tsx frontend/src/pages/Library.test.tsx
git commit -m "feat(frontend): passages in the top bar, Flow range, drawer and library"
```

---

### Task 11: Frontend — guidance logic: cues, karaoke timing, mode help, help key

**Files:**
- Create: `frontend/src/lib/text.ts`, `frontend/src/lib/cue.ts`, `frontend/src/lib/cue.test.ts`, `frontend/src/lib/karaoke.ts`, `frontend/src/lib/karaoke.test.ts`, `frontend/src/lib/modeHelp.ts`, `frontend/src/lib/modeHelp.test.ts`
- Modify: `frontend/src/lib/keys.ts`, `frontend/src/lib/keys.test.ts`

**Interfaces:**
- Consumes: `EchoState` (`lib/echo`), `FlowSub` (`lib/flow`), `GuidedStep` (`lib/guided`), `AlignSpan`, `Segment`, `Mode` (`api/types`).
- Produces (used by Tasks 13, 14, 17):
  - `lib/text.ts`: `isPunct(ch: string): boolean` (same set as the backend's `PUNCT`), `speechChars(text: string): string[]`
  - `lib/cue.ts`: `type CueTone`, `interface Cue { icon; text; tone }`, `type CuePhase = 'ready' | 'listen' | 'speak' | 'along' | 'review' | 'done'`, `interface CueState { phase; guided?; error?: boolean }`, `cueFor(mode: Mode, s: CueState): Cue`, `interface PageActivity { mode; echo; runKind: 'chorus' | 'flow' | 'guided' | null; guided; hasTake; flowPhase: 'setup' | 'running' | 'summary'; flowSub; flowTurn: boolean }`, `cuePhase(a: PageActivity): CuePhase`
  - `lib/karaoke.ts`: `ClipSpan { start; end }`, `Wipe { tone: 'ref' | 'ghost'; progress: number }`, `CountIn { start; end }`, `COUNT_IN_S = 1.5`, `MIN_COUNT_IN_GAP_S = 0.5`, `clipSpans(spans, clipStart): ClipSpan[]`, `wipeProgress(spans, t): number`, `ghostProgress(spans, elapsed, rate): number`, `countInWindow(startAt, gapBefore): CountIn | null`, `countInDots(w, t): number`, `charFill(text, progress): number[]`, `nextLineStart(cur, next, rate): { at: number; gap: number }`, `stageWipe(i: StageWipeInput): { wipe: Wipe | null; dots: number }`, `flowWipe(i: FlowWipeInput): { wipe: Wipe | null; dots: number; turnLeft: number | null }`
  - `lib/modeHelp.ts`: `MODES: Mode[]`, `modeName(m: Mode): string`, `modeHelp(m: Mode, chorusPasses: number): string`, `KEY_HELP: [string, string][]`
  - `lib/keys.ts`: `Action` gains `'help'`; `KEYMAP['?'] = 'help'`

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/cue.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import { cueFor, cuePhase, type PageActivity } from './cue'

describe('cueFor', () => {
  it.each([
    ['echo', 'ready', '⏸', 'Ready — Enter to start', 'neutral'],
    ['echo', 'listen', '🎧', 'Listen', 'ref'],
    ['echo', 'speak', '🗣', 'Your turn — speak now', 'you'],
    ['echo', 'review', '🎧', 'Listen — the original, then you', 'ref'],
    ['echo', 'done', '✓', 'Done — → for the next sentence, Enter to try again', 'ok'],
    ['chorus', 'ready', '⏸', 'Ready — Enter to start', 'neutral'],
    ['chorus', 'listen', '🎧', 'Listen', 'ref'],
    ['chorus', 'along', '🎤', 'Speak along', 'you'],
    ['chorus', 'review', '🎧', 'Listen — the original, then you', 'ref'],
    ['chorus', 'done', '✓', 'Done — → for the next sentence, Enter to try again', 'ok'],
    ['flow', 'ready', '⏸', 'Ready — Enter to start', 'neutral'],
    ['flow', 'listen', '🎧', 'Listen', 'ref'],
    ['flow', 'speak', '🗣', 'Your turn — speak now', 'you'],
    ['flow', 'along', '🎤', 'Speak along', 'you'],
    ['flow', 'done', '✓', 'Done — Enter to run it again', 'ok'],
    ['guided', 'listen', '🎧', 'Listen', 'ref'],
    ['guided', 'along', '🎤', 'Whisper along', 'you'],
    ['guided', 'speak', '🗣', 'Your turn — say it without the text', 'you'],
    ['guided', 'review', '🎧', 'Listen — the original, then you', 'ref'],
  ] as const)('%s / %s', (mode, phase, icon, text, tone) => {
    expect(cueFor(mode, { phase })).toEqual({ icon, text, tone })
  })
  it('Guided ready names the step Enter starts', () => {
    expect(cueFor('guided', { phase: 'ready', guided: 'listen' }).text).toBe('Ready — Enter to listen')
    expect(cueFor('guided', { phase: 'ready', guided: 'whisper' }).text).toBe('Ready — Enter, then whisper along')
    expect(cueFor('guided', { phase: 'ready', guided: 'record' }).text).toBe('Ready — Enter, then say it without the text')
  })
  it('an error turns the cue red in every mode', () => {
    for (const m of ['echo', 'chorus', 'flow', 'guided'] as const) {
      expect(cueFor(m, { phase: 'listen', error: true })).toEqual({ icon: '⚠', text: 'Something went wrong — see the message below', tone: 'bad' })
    }
  })
})

describe('cuePhase', () => {
  const base: PageActivity = { mode: 'echo', echo: 'idle', runKind: null, guided: 'listen', hasTake: false, flowPhase: 'setup', flowSub: 'after', flowTurn: false }
  it.each([
    [{}, 'ready'],
    [{ hasTake: true }, 'done'],
    [{ echo: 'playing' }, 'listen'],
    [{ echo: 'recording' }, 'speak'],
    [{ echo: 'uploading' }, 'review'],
    [{ echo: 'playback' }, 'review'],
    [{ mode: 'chorus', runKind: 'chorus', echo: 'recording' }, 'along'],
    [{ mode: 'guided', runKind: 'guided', guided: 'listen' }, 'listen'],
    [{ mode: 'guided', runKind: 'guided', guided: 'whisper' }, 'along'],
    [{ mode: 'guided', echo: 'recording', guided: 'record' }, 'speak'],
    [{ mode: 'guided', hasTake: true }, 'ready'],
    [{ mode: 'flow', flowPhase: 'running', flowSub: 'after' }, 'listen'],
    [{ mode: 'flow', flowPhase: 'running', flowSub: 'after', flowTurn: true }, 'speak'],
    [{ mode: 'flow', flowPhase: 'running', flowSub: 'along' }, 'along'],
    [{ mode: 'flow', flowPhase: 'summary' }, 'done'],
    [{ mode: 'flow', hasTake: true }, 'ready'],
  ] as const)('%o → %s', (over, want) => {
    expect(cuePhase({ ...base, ...over } as PageActivity)).toBe(want)
  })
})
```

`frontend/src/lib/karaoke.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import { charFill, clipSpans, countInDots, countInWindow, flowWipe, ghostProgress, nextLineStart, stageWipe, wipeProgress, type ClipSpan } from './karaoke'
import { isPunct, speechChars } from './text'

const spans: ClipSpan[] = [{ start: 0.1, end: 0.3 }, { start: 0.3, end: 0.3 }, { start: 0.5, end: 0.9 }]

describe('karaoke timing', () => {
  it('clip spans are relative to the clip start', () => {
    const s = clipSpans([{ ch: '你', start: 10.2, end: 10.5, conf: 1 }], 10)
    expect(s[0].start).toBeCloseTo(0.2); expect(s[0].end).toBeCloseTo(0.5)
    expect(clipSpans(null, 10)).toEqual([])
  })
  it('wipeProgress counts finished characters plus the fraction of the current one', () => {
    expect(wipeProgress(spans, 0)).toBe(0)
    expect(wipeProgress(spans, 0.2)).toBeCloseTo(0.5)
    expect(wipeProgress(spans, 0.3)).toBe(2)         // a zero-length span counts at once
    expect(wipeProgress(spans, 0.4)).toBe(2)         // holds in the pause
    expect(wipeProgress(spans, 0.7)).toBeCloseTo(2.5)
    expect(wipeProgress(spans, 5)).toBe(3)
    expect(wipeProgress([], 1)).toBe(0)              // no alignment: no wipe
  })
  it('ghostProgress replays the reference pace from the turn start, scaled by the rate', () => {
    expect(ghostProgress(spans, 0.2, 1)).toBe(2)
    expect(ghostProgress(spans, 0.2, 0.5)).toBeCloseTo(0.5)
    expect(ghostProgress([], 1, 1)).toBe(0)
  })
  it('count-in: 1.5 s before the start, omitted after a gap under 0.5 s', () => {
    const w = countInWindow(10, Infinity)!
    expect(w).toEqual({ start: 8.5, end: 10 })
    expect(countInWindow(10, 0.4)).toBeNull()
    expect(countInWindow(10, 0.5)).not.toBeNull()
    expect([8.4, 8.5, 9.0, 9.6, 10].map((t) => countInDots(w, t))).toEqual([0, 3, 2, 1, 0])
    expect(countInDots(null, 9)).toBe(0)
  })
  it('charFill colours punctuation with the character before it', () => {
    expect(charFill('你好，吗', 1.5)).toEqual([1, 0.5, 0, 0])
    expect(charFill('你，好', 1)).toEqual([1, 1, 0])
  })
  it('punctuation matches the backend set', () => {
    expect(['，', '。', ' ', '　', '「', '』', '%'].map(isPunct)).toEqual([true, true, true, true, true, true, false])
    expect(speechChars('你好，世界。')).toEqual(['你', '好', '世', '界'])
  })
  it('nextLineStart: when the next line speaks, and the silence before it', () => {
    const cur = { start_s: 10, end_s: 12, ref_alignment_json: [{ ch: '你', start: 10.2, end: 11.5, conf: 1 }] }
    const next = { start_s: 12, end_s: 14, ref_alignment_json: [{ ch: '好', start: 12.3, end: 13, conf: 1 }] }
    const a = nextLineStart(cur, next, 1)
    expect(a.at).toBeCloseTo(2.3); expect(a.gap).toBeCloseTo(0.8)
    const b = nextLineStart(cur, next, 0.5)
    expect(b.at).toBeCloseTo(4.6); expect(b.gap).toBeCloseTo(1.6)
    expect(nextLineStart({ ...cur, ref_alignment_json: null }, { ...next, ref_alignment_json: null }, 1)).toEqual({ at: 2, gap: 0 })
  })
})

describe('stageWipe (Echo, Chorus, Guided)', () => {
  it('colours the sentence while the reference plays', () => {
    const r = stageWipe({ spans, refPlaying: true, refHead: 0.2, turnStart: null, now: 0, rate: 1 })
    expect(r.wipe?.tone).toBe('ref'); expect(r.wipe?.progress).toBeCloseTo(0.5); expect(r.dots).toBe(0)
  })
  it('an Echo take: count-in dots first, then the ghost wipe', () => {
    expect(stageWipe({ spans, refPlaying: false, refHead: null, turnStart: 100, now: 100.5, rate: 1 })).toEqual({ wipe: null, dots: 2 })
    expect(stageWipe({ spans, refPlaying: false, refHead: null, turnStart: 100, now: 101.7, rate: 1 })).toEqual({ wipe: { tone: 'ghost', progress: 2 }, dots: 0 })
  })
  it('no alignment: no wipe (the cue line still shows)', () => {
    expect(stageWipe({ spans: [], refPlaying: true, refHead: 0.5, turnStart: null, now: 0, rate: 1 })).toEqual({ wipe: null, dots: 0 })
  })
})

describe('flowWipe', () => {
  const base = { spans, clipDuration: 2, turn: null, now: 0, rate: 1, next: null }
  it('after, while the clip plays: the colour wipe, and count-in dots over its last 1.5 s', () => {
    const a = flowWipe({ ...base, sub: 'after', clipTime: 0.2 })
    expect(a.wipe?.tone).toBe('ref'); expect(a.wipe?.progress).toBeCloseTo(0.5); expect(a.dots).toBe(0)
    expect(flowWipe({ ...base, sub: 'after', clipTime: 1.0 }).dots).toBe(2)
    expect(flowWipe({ ...base, sub: 'after', clipTime: 1.5, rate: 0.5 }).dots).toBe(2) // 3 s of 4 s real time
  })
  it('after, during the turn: the ghost wipe and the turn bar', () => {
    expect(flowWipe({ ...base, sub: 'after', clipTime: null, turn: { startedAt: 50, duration: 2 }, now: 51 }))
      .toEqual({ wipe: { tone: 'ghost', progress: 3 }, dots: 0, turnLeft: 0.5 })
  })
  it('along: count-in before the next line only when there is a real pause', () => {
    expect(flowWipe({ ...base, sub: 'along', clipTime: 1.5, next: { at: 2.5, gap: 0.3 } }).dots).toBe(0)
    expect(flowWipe({ ...base, sub: 'along', clipTime: 1.5, next: { at: 2.5, gap: 0.8 } }).dots).toBe(2)
  })
  it('nothing playing: nothing to draw', () => {
    expect(flowWipe({ ...base, sub: 'after', clipTime: null })).toEqual({ wipe: null, dots: 0, turnLeft: null })
  })
})
```

`frontend/src/lib/modeHelp.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import { KEY_HELP, MODES, modeHelp, modeName } from './modeHelp'

describe('mode help', () => {
  it('uses the spec texts, with the Chorus pass count', () => {
    expect(modeHelp('echo', 5)).toBe('One sentence at a time: listen, then repeat it on your own. You hear the original and your take back to back.')
    expect(modeHelp('chorus', 3)).toBe('Speak at the same time as the sentence, 3 times in a row. Only the last pass is recorded.')
    expect(modeHelp('flow', 5)).toBe('Shadow a whole passage without stopping. After: each sentence plays, then you repeat it in the pause. Along: speak at the same time as the audio (use headphones).')
    expect(modeHelp('guided', 5)).toBe('Four steps per sentence: listen → whisper along with the text → say it with the text hidden → next.')
  })
  it('lists every mode and the help key', () => {
    expect(MODES.map(modeName)).toEqual(['Echo', 'Chorus', 'Flow', 'Guided'])
    expect(KEY_HELP.map(([k]) => k)).toContain('?')
  })
})
```

Append to `frontend/src/lib/keys.test.ts` (inside its `describe`):
```ts
  it('? opens the help', () => {
    expect(actionForKey({ key: '?', target: document.createElement('div'), ctrlKey: false, metaKey: false, altKey: false, repeat: false })).toBe('help')
  })
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/lib/cue.test.ts src/lib/karaoke.test.ts src/lib/modeHelp.test.ts src/lib/keys.test.ts`
Expected: FAIL — the new modules cannot be resolved; `actionForKey` returns null for `?`.

- [ ] **Step 3: Implement**

`frontend/src/lib/text.ts`:
```ts
// Punctuation and spacing exactly as the backend's PUNCT (shadow/ingest/text.py): the backend aligns and romanises
// every other character, so spans and syllables line up with the characters this does not skip.
const PUNCT = new Set([...'，。！？；：、“”‘’（）《》〈〉【】…—·,.!?;:()"\'[]<>-~～ 　\n\t「」『』'])
export const isPunct = (ch: string): boolean => PUNCT.has(ch)
export const speechChars = (text: string): string[] => [...text].filter((c) => !isPunct(c))
```

`frontend/src/lib/cue.ts`:
```ts
import type { Mode } from '../api/types'
import type { EchoState } from './echo'
import type { FlowSub } from './flow'
import type { GuidedStep } from './guided'

export type CueTone = 'ref' | 'you' | 'neutral' | 'ok' | 'bad'
export interface Cue { icon: string; text: string; tone: CueTone }
// What the learner should be doing right now (addendum §6.2).
export type CuePhase = 'ready' | 'listen' | 'speak' | 'along' | 'review' | 'done'
export interface CueState { phase: CuePhase; guided?: GuidedStep; error?: boolean }

const GUIDED_READY: Record<GuidedStep, string> = {
  listen: 'Ready — Enter to listen', whisper: 'Ready — Enter, then whisper along', record: 'Ready — Enter, then say it without the text',
}

// The one-line instruction above the sentence; the record button keeps only a short label. Echo and Chorus "done"
// names the real keys (→ moves on, Enter records again); Flow's Enter runs the range again.
export function cueFor(mode: Mode, s: CueState): Cue {
  if (s.error) return { icon: '⚠', text: 'Something went wrong — see the message below', tone: 'bad' }
  switch (s.phase) {
    case 'listen': return { icon: '🎧', text: 'Listen', tone: 'ref' }
    case 'speak': return { icon: '🗣', text: mode === 'guided' ? 'Your turn — say it without the text' : 'Your turn — speak now', tone: 'you' }
    case 'along': return { icon: '🎤', text: mode === 'guided' ? 'Whisper along' : 'Speak along', tone: 'you' }
    case 'review': return { icon: '🎧', text: 'Listen — the original, then you', tone: 'ref' }
    case 'done': return { icon: '✓', text: mode === 'flow' ? 'Done — Enter to run it again' : 'Done — → for the next sentence, Enter to try again', tone: 'ok' }
    case 'ready': return { icon: '⏸', text: mode === 'guided' ? GUIDED_READY[s.guided ?? 'listen'] : 'Ready — Enter to start', tone: 'neutral' }
  }
}

export interface PageActivity {
  mode: Mode; echo: EchoState; runKind: 'chorus' | 'flow' | 'guided' | null; guided: GuidedStep; hasTake: boolean
  flowPhase: 'setup' | 'running' | 'summary'; flowSub: FlowSub; flowTurn: boolean // flowTurn: Flow after's speaking window is open
}

// The cue phase from the practice page's state.
export function cuePhase(a: PageActivity): CuePhase {
  if (a.mode === 'flow') {
    if (a.flowPhase === 'running') return a.flowSub === 'along' ? 'along' : a.flowTurn ? 'speak' : 'listen'
    return a.flowPhase === 'summary' ? 'done' : 'ready'
  }
  if (a.runKind === 'chorus') return 'along'
  if (a.runKind === 'guided') return a.guided === 'whisper' ? 'along' : 'listen'
  if (a.echo === 'recording') return 'speak'
  if (a.echo === 'playing') return 'listen'
  if (a.echo === 'playback' || a.echo === 'uploading') return 'review'
  if (a.mode === 'guided') return 'ready'
  return a.hasTake ? 'done' : 'ready'
}
```

`frontend/src/lib/karaoke.ts`:
```ts
import type { AlignSpan, Segment } from '../api/types'
import type { FlowSub } from './flow'
import { isPunct } from './text'

// Karaoke cues (addendum §6.5): all the timing logic, so the components only draw.

export interface ClipSpan { start: number; end: number }          // clip-relative seconds, one per speech character
export interface Wipe { tone: 'ref' | 'ghost'; progress: number } // progress: speech characters coloured, 0 … n
export interface CountIn { start: number; end: number }

export const COUNT_IN_S = 1.5
export const MIN_COUNT_IN_GAP_S = 0.5

// ref_alignment_json is source-absolute; the clip starts at the segment's start_s.
export function clipSpans(spans: AlignSpan[] | null | undefined, clipStart: number): ClipSpan[] {
  return (spans ?? []).map((s) => ({ start: s.start - clipStart, end: s.end - clipStart }))
}

// Speech characters coloured at clip time `t`: those whose span has ended plus the fraction of the one in progress.
// It holds between characters, and a zero-length span counts as soon as it is reached.
export function wipeProgress(spans: ClipSpan[], t: number): number {
  let p = 0
  for (const s of spans) {
    if (t >= s.end) { p += 1; continue }
    if (t > s.start) p += (t - s.start) / (s.end - s.start)
    break
  }
  return p
}

// The ghost wipe: the reference's pace replayed from the start of the learner's turn (`elapsed` seconds ago), slowed
// with the playback rate (at 0.75× the learner gets 1 / 0.75 as long).
export function ghostProgress(spans: ClipSpan[], elapsed: number, rate: number): number {
  return spans.length ? wipeProgress(spans, spans[0].start + elapsed * rate) : 0
}

// The 1.5 s before the learner must start at `startAt` (any clock, seconds); null when the gap before that moment is
// under 0.5 s (no room to count in: the learner is still speaking the previous line).
export function countInWindow(startAt: number, gapBefore: number): CountIn | null {
  return gapBefore < MIN_COUNT_IN_GAP_S ? null : { start: startAt - COUNT_IN_S, end: startAt }
}

// Dots still showing at time `t`: 3 → 1 across the window, 0 outside it.
export function countInDots(w: CountIn | null, t: number): number {
  if (!w || t < w.start || t >= w.end) return 0
  return Math.min(3, Math.ceil((3 * (w.end - t)) / (w.end - w.start)))
}

// Per character (code point) of `text`: how much of it the wipe covers (0 … 1) when `progress` speech characters are
// coloured. Punctuation is coloured together with the speech character before it.
export function charFill(text: string, progress: number): number[] {
  const out: number[] = []
  let k = 0, last = 0
  for (const ch of text) {
    if (isPunct(ch)) { out.push(last >= 1 ? 1 : 0); continue }
    last = Math.max(0, Math.min(1, progress - k))
    out.push(last)
    k++
  }
  return out
}

type SegTiming = Pick<Segment, 'start_s' | 'end_s' | 'ref_alignment_json'>
// Flow along: when the next line's speech starts (real seconds from the start of the current clip) and the silence
// before it (real seconds), from the alignment when there is one, else from the clip bounds.
export function nextLineStart(cur: SegTiming, next: SegTiming, rate: number): { at: number; gap: number } {
  const al = cur.ref_alignment_json ?? []
  const curSpeechEnd = al.length ? al[al.length - 1].end : cur.end_s
  const lead = (next.ref_alignment_json?.[0]?.start ?? next.start_s) - next.start_s
  return { at: (cur.end_s - cur.start_s + lead) / rate, gap: (cur.end_s - curSpeechEnd + lead) / rate }
}

export interface StageWipeInput {
  spans: ClipSpan[]; refPlaying: boolean; refHead: number | null
  turnStart: number | null // performance-clock second an Echo take began, else null
  now: number; rate: number
}
// Echo, Chorus, Guided: the colour wipe while the reference plays; for an Echo take, 1.5 s of count-in dots from
// the moment it starts recording, then the ghost wipe.
export function stageWipe(i: StageWipeInput): { wipe: Wipe | null; dots: number } {
  if (i.turnStart != null) {
    const start = i.turnStart + COUNT_IN_S
    const elapsed = i.now - start
    return {
      wipe: elapsed >= 0 && i.spans.length ? { tone: 'ghost', progress: ghostProgress(i.spans, elapsed, i.rate) } : null,
      dots: countInDots(countInWindow(start, Infinity), i.now),
    }
  }
  if (i.refPlaying && i.spans.length) return { wipe: { tone: 'ref', progress: wipeProgress(i.spans, i.refHead ?? 0) }, dots: 0 }
  return { wipe: null, dots: 0 }
}

export interface FlowWipeInput {
  spans: ClipSpan[]; sub: FlowSub
  clipTime: number | null; clipDuration: number                    // media seconds of the current clip
  turn: { startedAt: number; duration: number } | null              // after: the speaking window (performance clock)
  now: number; rate: number
  next: { at: number; gap: number } | null                          // along: nextLineStart() of the next line
}
// Flow: the colour wipe while a clip plays, count-in dots before the learner's turn (after: the clip's last 1.5 s;
// along: before each new line), and in after's turn the ghost wipe and the share of the turn left (turn bar).
export function flowWipe(i: FlowWipeInput): { wipe: Wipe | null; dots: number; turnLeft: number | null } {
  if (i.turn) {
    const elapsed = Math.max(0, i.now - i.turn.startedAt)
    return {
      wipe: i.spans.length ? { tone: 'ghost', progress: ghostProgress(i.spans, elapsed, i.rate) } : null,
      dots: 0, turnLeft: i.turn.duration > 0 ? Math.max(0, 1 - elapsed / i.turn.duration) : 0,
    }
  }
  if (i.clipTime == null) return { wipe: null, dots: 0, turnLeft: null }
  const w = i.sub === 'after' ? countInWindow(i.clipDuration / i.rate, Infinity) : i.next ? countInWindow(i.next.at, i.next.gap) : null
  return {
    wipe: i.spans.length ? { tone: 'ref', progress: wipeProgress(i.spans, i.clipTime) } : null,
    dots: countInDots(w, i.clipTime / i.rate), turnLeft: null,
  }
}
```

`frontend/src/lib/modeHelp.ts`:
```ts
import type { Mode } from '../api/types'

export const MODES: Mode[] = ['echo', 'chorus', 'flow', 'guided']
export const modeName = (m: Mode): string => m[0].toUpperCase() + m.slice(1)

// Hover text on each mode tab and the help overlay (addendum §6.1).
export function modeHelp(m: Mode, chorusPasses: number): string {
  switch (m) {
    case 'echo': return 'One sentence at a time: listen, then repeat it on your own. You hear the original and your take back to back.'
    case 'chorus': return `Speak at the same time as the sentence, ${chorusPasses} times in a row. Only the last pass is recorded.`
    case 'flow': return 'Shadow a whole passage without stopping. After: each sentence plays, then you repeat it in the pause. Along: speak at the same time as the audio (use headphones).'
    case 'guided': return 'Four steps per sentence: listen → whisper along with the text → say it with the text hidden → next.'
  }
}

export const KEY_HELP: [string, string][] = [
  ['Space', 'Play the sentence'], ['Enter', 'Start or stop: record (Echo), Chorus, Flow, the next Guided step'],
  ['C', 'Chorus'], ['← →', 'Previous / next sentence'], ['R', 'Replay your take'], ['S', '0.75× speed'],
  ['T  P  E', 'Hanzi, pinyin, translation'], ['F', 'Flag the sentence'], ['A', 'Send to Anki'], ['L', 'Lesson list'], ['?', 'This help'],
]
```

`frontend/src/lib/keys.ts`: add `| 'help'` to `Action` and `'?': 'help'` to `KEYMAP`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/lib && npx eslint src`
Expected: PASS; no eslint errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/text.ts frontend/src/lib/cue.ts frontend/src/lib/cue.test.ts frontend/src/lib/karaoke.ts frontend/src/lib/karaoke.test.ts frontend/src/lib/modeHelp.ts frontend/src/lib/modeHelp.test.ts frontend/src/lib/keys.ts frontend/src/lib/keys.test.ts
git commit -m "feat(frontend): cue, karaoke timing and mode help logic"
```

---

### Task 12: Frontend — reference volume, guide level and the headphones hint

**Files:**
- Create: `frontend/src/lib/volume.ts`, `frontend/src/lib/volume.test.ts`, `frontend/src/components/VolumeSliders.tsx`
- Modify: `frontend/src/store/settings.ts`, `frontend/src/store/settings.test.ts`, `frontend/src/audio/player.ts`, `frontend/src/audio/player.test.ts`, `frontend/src/components/Transport.tsx`, `frontend/src/components/FlowView.tsx` (`FlowTransport` only), `frontend/src/pages/Practice.tsx`, `frontend/src/pages/Practice.test.tsx`

**Interfaces:**
- Consumes: `FlowSub`, `Mode`.
- Produces:
  - settings: `referenceVolume: number` (0–1, default 1), `guideLevel: number` (0–1, default 0.5), `helpSeen: boolean` (default false), set with `useSettings.getState().set({...})`
  - `ClipPlayer.setVolume(v: number): void` (clamped to 0–1; applies to the element playing and every later one)
  - `clamp01(v: number): number`, `playbackVolume(o: { speakingAlong: boolean; referenceVolume: number; guideLevel: number }): number`, `guideApplies(mode: Mode, flowSub: FlowSub): boolean`
  - `export interface VolumeControls { reference: number; guide: number | null; onReference: (v: number) => void; onGuide: (v: number) => void }` and `VolumeSliders({ volume })` (sliders labelled "Reference volume" and "Guide level")
  - `Transport` prop `volume: VolumeControls`; `FlowTransport` props `volume: VolumeControls`, `hint: string`

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/volume.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import { clamp01, guideApplies, playbackVolume } from './volume'

describe('volume', () => {
  it('plays the reference at its volume, and at the guide level of it while speaking along', () => {
    expect(playbackVolume({ speakingAlong: false, referenceVolume: 0.8, guideLevel: 0.5 })).toBeCloseTo(0.8)
    expect(playbackVolume({ speakingAlong: true, referenceVolume: 0.8, guideLevel: 0.5 })).toBeCloseTo(0.4)
    expect(playbackVolume({ speakingAlong: true, referenceVolume: 2, guideLevel: -1 })).toBe(0)
  })
  it('the guide level applies to Chorus and Flow along only', () => {
    expect([guideApplies('chorus', 'after'), guideApplies('flow', 'along'), guideApplies('flow', 'after'), guideApplies('echo', 'along')]).toEqual([true, true, false, false])
  })
  it('clamps', () => { expect([clamp01(-0.1), clamp01(0.3), clamp01(1.5), clamp01(Number.NaN)]).toEqual([0, 0.3, 1, 0]) })
})
```

Append to `frontend/src/store/settings.test.ts` (inside its `describe`):
```ts
  it('has volume and help defaults and persists them', () => {
    const s = useSettings.getState()
    expect([s.referenceVolume, s.guideLevel, s.helpSeen]).toEqual([1, 0.5, false])
    s.set({ referenceVolume: 0.6, guideLevel: 0.3, helpSeen: true })
    const raw = JSON.parse(localStorage.getItem('shadow.settings')!)
    expect([raw.state.referenceVolume, raw.state.guideLevel, raw.state.helpSeen]).toEqual([0.6, 0.3, true])
  })
```

Append to `frontend/src/audio/player.test.ts` inside `describe('ClipPlayer', …)`:
```ts
  it('plays every clip at the set volume and changes the one playing at once', async () => {
    player.setVolume(0.4)
    const p = player.play('vol.mp3', 1)
    await Promise.resolve()
    const a = [...audioElements.keys()].find((el) => audioElements.get(el)?.url === 'vol.mp3')!
    expect(a.volume).toBeCloseTo(0.4)
    player.setVolume(1.5)
    expect(a.volume).toBe(1)
    player.stop(); await p
  })
```

In `frontend/src/pages/Practice.test.tsx`:
- in the hoisted `player` object add `setVolume: vi.fn(),`;
- inside `describe('Chorus', …)` add:
```tsx
    it('plays the passes at the guide level of the reference volume and shows the headphones hint once', async () => {
      useSettings.setState({ referenceVolume: 0.8, guideLevel: 0.5 })
      const atPlay: number[] = []
      h.player.play.mockImplementation(() => { atPlay.push(h.player.setVolume.mock.lastCall![0] as number); return Promise.resolve() })
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      await waitFor(() => expect(h.player.setVolume).toHaveBeenLastCalledWith(0.8))
      press('c')
      await waitFor(() => expect(h.playSequence).toHaveBeenCalled())
      expect(atPlay.length).toBeGreaterThan(0)
      atPlay.forEach((v) => expect(v).toBeCloseTo(0.4))
      expect(screen.getByText('Use headphones — the mic would pick up the reference')).toBeInTheDocument()
      await waitFor(() => expect(h.player.setVolume).toHaveBeenLastCalledWith(0.8)) // the takes play at the reference volume
      useSettings.setState({ referenceVolume: 1, guideLevel: 0.5 })
    })
```
- inside `describe('Flow', …)` add:
```tsx
    it('along plays every clip at the guide level and hints at headphones', async () => {
      useSettings.setState({ referenceVolume: 0.8, guideLevel: 0.5 })
      const atPlay: number[] = []
      h.player.play.mockImplementation(() => { atPlay.push(h.player.setVolume.mock.lastCall![0] as number); h.clock.t += 2; return Promise.resolve() })
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('along')
      await screen.findByText(/Flow finished/)
      expect(atPlay).toHaveLength(2)
      atPlay.forEach((v) => expect(v).toBeCloseTo(0.4))
      expect(screen.getByText('Use headphones — the mic would pick up the reference')).toBeInTheDocument()
      useSettings.setState({ referenceVolume: 1, guideLevel: 0.5 })
    })
```
- append at the top level of `describe('<Practice>', …)`:
```tsx
  describe('volume', () => {
    afterEach(() => { useSettings.setState({ referenceVolume: 1, guideLevel: 0.5 }) })

    it('shows the guide level only in Chorus and Flow along', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      expect(screen.getByLabelText('Reference volume')).toBeInTheDocument()
      expect(screen.queryByLabelText('Guide level')).toBeNull()
      fireEvent.click(screen.getByRole('button', { name: 'Chorus' }))
      expect(await screen.findByLabelText('Guide level')).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Flow' }))
      await waitFor(() => expect(screen.queryByLabelText('Guide level')).toBeNull()) // Flow starts in after
      fireEvent.click(screen.getByRole('button', { name: 'along' }))
      expect(screen.getByLabelText('Guide level')).toBeInTheDocument()
    })

    it('the reference volume is saved in settings and applied to the player', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      fireEvent.change(screen.getByLabelText('Reference volume'), { target: { value: '60' } })
      expect(useSettings.getState().referenceVolume).toBeCloseTo(0.6)
      await waitFor(() => expect(h.player.setVolume).toHaveBeenLastCalledWith(0.6))
    })
  })
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/lib/volume.test.ts src/store/settings.test.ts src/audio/player.test.ts src/pages/Practice.test.tsx`
Expected: FAIL — `./volume` cannot be resolved; `referenceVolume` undefined; `player.setVolume is not a function`; no volume sliders.

- [ ] **Step 3: Settings, player and the volume helpers**

`frontend/src/store/settings.ts`: add to `SettingsState` (after `textPrefs`)
```ts
  referenceVolume: number   // 0–1: every reference playback and your own takes (addendum §7)
  guideLevel: number        // 0–1 of the reference volume while speaking along (Chorus, Flow along)
  helpSeen: boolean         // the practice help overlay has opened once
```
and to `defaults`: `referenceVolume: 1, guideLevel: 0.5, helpSeen: false,`.

`frontend/src/audio/player.ts` in `ClipPlayer`: add the field `private vol = 1` next to `private active`, add the method
```ts
  // Volume (0…1) of the clip playing and of every later one.
  setVolume(v: number) {
    this.vol = Math.max(0, Math.min(1, Number.isFinite(v) ? v : 1))
    if (this.current) this.current.volume = this.vol
  }
```
and in `run()` change `const a = this.el(url); this.current = a; a.playbackRate = rate; a.currentTime = fromS` to
```ts
    const a = this.el(url); this.current = a; a.playbackRate = rate; a.volume = this.vol; a.currentTime = fromS
```

`frontend/src/lib/volume.ts`:
```ts
import type { Mode } from '../api/types'
import type { FlowSub } from './flow'

export const clamp01 = (v: number): number => (Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0)

// Playback volume now (addendum §7): while the learner speaks along (Chorus, Flow along) the reference plays at the
// guide level of the reference volume; otherwise, and for the learner's own takes, at the reference volume.
export function playbackVolume(o: { speakingAlong: boolean; referenceVolume: number; guideLevel: number }): number {
  const ref = clamp01(o.referenceVolume)
  return o.speakingAlong ? ref * clamp01(o.guideLevel) : ref
}

// The guide-level slider is shown in these modes only.
export const guideApplies = (mode: Mode, flowSub: FlowSub): boolean => mode === 'chorus' || (mode === 'flow' && flowSub === 'along')
```

`frontend/src/components/VolumeSliders.tsx`:
```tsx
export interface VolumeControls { reference: number; guide: number | null; onReference: (v: number) => void; onGuide: (v: number) => void }

// Reference volume, and the guide level (shown only where it applies: guide null hides it). Values 0…1, sliders in %.
export default function VolumeSliders({ volume }: { volume: VolumeControls }) {
  const pct = (v: number) => Math.round(v * 100)
  return (<>
    {/* blur after a drag so Space/arrows go back to the page shortcuts */}
    <label className="text-xs text-fgdim flex items-center gap-1" title="Reference volume">🔊 {pct(volume.reference)}%
      <input type="range" aria-label="Reference volume" min={0} max={100} step={5} value={pct(volume.reference)}
        onChange={(e) => volume.onReference(Number(e.target.value) / 100)} onPointerUp={(e) => e.currentTarget.blur()} /></label>
    {volume.guide != null && (
      <label className="text-xs text-fgdim flex items-center gap-1" title="Reference level while you speak along, as a share of the reference volume">guide {pct(volume.guide)}%
        <input type="range" aria-label="Guide level" min={0} max={100} step={5} value={pct(volume.guide)}
          onChange={(e) => volume.onGuide(Number(e.target.value) / 100)} onPointerUp={(e) => e.currentTarget.blur()} /></label>)}
  </>)
}
```

- [ ] **Step 4: Transports**

`frontend/src/components/Transport.tsx`: add `import VolumeSliders, { type VolumeControls } from './VolumeSliders'`, add `volume: VolumeControls` to `Props` and to the destructured parameters, and insert `<VolumeSliders volume={volume} />` right after the `0.75×` button.

In `frontend/src/components/FlowView.tsx` add `import VolumeSliders, { type VolumeControls } from './VolumeSliders'` and replace `FlowTransport` with:
```tsx
// Flow mode while running: ■ stop (Enter) · skip (→) · speed · volume. Pause is not in v1.
export function FlowTransport({ rate, onRate, sub, onStop, onSkip, error, hint, volume }: {
  rate: number; onRate: (r: number) => void; sub: FlowSub; onStop: () => void; onSkip: () => void; error: string; hint: string; volume: VolumeControls
}) {
  const b = 'px-3 py-1 rounded bg-panel2 text-sm'
  return (
    <div className="border-t border-line p-3 text-center space-y-1">
      <div className="flex justify-center gap-2 items-center">
        <button className={`${b} bg-[#5a1f26] text-[#ffd7db]`} onClick={onStop} title="Stop and save the finished sentences (Enter)">■ stop</button>
        <button className={b} onClick={onSkip} title="Skip this sentence (→)">skip ▸▸</button>
        <label className="text-xs text-fgdim flex items-center gap-1">{rate.toFixed(2)}×<input type="range" aria-label="Playback speed" min={0.6} max={1} step={0.05} value={rate}
          onChange={(e) => onRate(Number(e.target.value))} onPointerUp={(e) => e.currentTarget.blur()} /></label>
        <button className={b} onClick={() => onRate(rate === 0.75 ? 1 : 0.75)}>0.75×</button>
        <span className="text-xs text-fgdim">{sub}</span>
        <VolumeSliders volume={volume} />
      </div>
      {hint && <p className="text-xs text-warn">{hint}</p>}
      {error && <p className="text-xs text-bad" role="alert">{error}</p>}
    </div>
  )
}
```

- [ ] **Step 5: Practice**

`frontend/src/pages/Practice.tsx`:
- imports: `import { clamp01, guideApplies, playbackVolume } from '../lib/volume'` and `import type { VolumeControls } from '../components/VolumeSliders'`;
- below `const MOVE_ON = …` add `const HEADPHONES = 'Use headphones — the mic would pick up the reference'`;
- below `const exporting = useRef(false)` add `const headphonesHinted = useRef(false)          // the headphones hint shows once per visit`;
- after the effect `useEffect(() => { setGuided('listen') }, [segId, st.mode])` add:
```tsx
  // Reference volume, or its guide level while the learner speaks along (addendum §7); follows the sliders live.
  const speakingAlong = runKind === 'chorus' || (runKind === 'flow' && flow.state.sub === 'along')
  const playVolume = playbackVolume({ speakingAlong, referenceVolume: settings.referenceVolume, guideLevel: settings.guideLevel })
  useEffect(() => { player.setVolume(playVolume) }, [player, playVolume])
```
- replace `beginRun`, `endRun` and `abortRun` with:
```tsx
  function beginRun(kind: RunKind): AbortController {
    const ctrl = new AbortController()
    runRef.current = { kind, ctrl }; setRunKind(kind)
    applyVolume(kind === 'chorus' || (kind === 'flow' && flow.state.sub === 'along'))
    return ctrl
  }
  function endRun(ctrl: AbortController) { if (runRef.current?.ctrl === ctrl) { runRef.current = null; setRunKind(null); applyVolume(false) } }
  function abortRun() { const r = runRef.current; if (!r) return; runRef.current = null; setRunKind(null); applyVolume(false); r.ctrl.abort() }
  // At once, before the run's first clip (the effect above follows a render later).
  function applyVolume(along: boolean) {
    const s = useSettings.getState()
    player.setVolume(playbackVolume({ speakingAlong: along, referenceVolume: s.referenceVolume, guideLevel: s.guideLevel }))
  }
  function hintHeadphones() {
    if (headphonesHinted.current) return
    headphonesHinted.current = true
    usePractice.getState().setHint(HEADPHONES)
  }
```
- in `chorus()` replace the two lines `stopPlayback(); setError('')` and `const run = beginRun('chorus'), { signal } = run` with
```tsx
    stopPlayback(); setError(''); hintHeadphones()
    const run = beginRun('chorus'), { signal } = run
```
- replace `startFlow` with:
```tsx
  function startFlow(from: number, to: number) {
    cancelActivity()
    if (flow.state.sub === 'along') hintHeadphones()
    void flow.start(from, to, flow.state.sub)
  }
```
- after `const range = flowRange()` add:
```tsx
  const volume: VolumeControls = {
    reference: settings.referenceVolume, guide: guideApplies(st.mode, fs.sub) ? settings.guideLevel : null,
    onReference: (v) => settings.set({ referenceVolume: clamp01(v) }), onGuide: (v) => settings.set({ guideLevel: clamp01(v) }),
  }
```
- add `volume={volume}` to `<Transport … />` and `hint={st.hint} volume={volume}` to `<FlowTransport … />`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run && npx eslint src`
Expected: PASS; no eslint errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/volume.ts frontend/src/lib/volume.test.ts frontend/src/components/VolumeSliders.tsx frontend/src/store/settings.ts frontend/src/store/settings.test.ts frontend/src/audio/player.ts frontend/src/audio/player.test.ts frontend/src/components/Transport.tsx frontend/src/components/FlowView.tsx frontend/src/pages/Practice.tsx frontend/src/pages/Practice.test.tsx
git commit -m "feat(frontend): reference volume, guide level while speaking along, headphones hint"
```

---
### Task 13: Frontend — cue line, mic meter, karaoke overlay, help overlay and tooltips (Echo, Chorus, Guided)

**Files:**
- Create: `frontend/src/components/CueLine.tsx`, `frontend/src/components/KaraokeSentence.tsx`, `frontend/src/components/KaraokeSentence.test.tsx`, `frontend/src/components/HelpOverlay.tsx`, `frontend/src/components/TopBar.test.tsx`, `frontend/src/lib/charRects.ts`, `frontend/src/lib/useNow.ts`, `frontend/src/audio/useMicLevel.ts`
- Modify: `frontend/src/components/Sentence.tsx` (export `SentenceProps`, `pRef`), `frontend/src/components/TopBar.tsx`, `frontend/src/audio/useMic.ts` (`level()`), `frontend/src/pages/Practice.tsx`, `frontend/src/pages/Practice.test.tsx`

**Interfaces:**
- Consumes: Task 11 (`cueFor`, `cuePhase`, `Cue`, `clipSpans`, `stageWipe`, `charFill`, `Wipe`, `MODES`, `modeName`, `modeHelp`, `KEY_HELP`, action `'help'`), Task 12 (`helpSeen` setting), Task 10 (`PassagePick`).
- Produces (Task 14 reuses the components):
  - `CueLine({ cue: Cue; level: number | null; dots?: number })` — `data-testid="cue-line"`; dots labelled `starting in N`; meter `role="meter"` named "Microphone level" when `level != null`
  - `KaraokeSentence(props: SentenceProps & { wipe: Wipe | null })` — wipe layer `data-testid="wipe"`; `GhostLine({ count: number; wipe: Wipe | null })` — `data-testid="ghost-line"`
  - `HelpOverlay({ chorusPasses: number; onClose: () => void })` — `role="dialog"` named "How to practise"; Esc or `?` closes
  - `charRects(p: HTMLElement, container: HTMLElement): (Rect | null)[]`, `interface Rect { left; top; width; height }`
  - `useNow(active: boolean): number` (seconds, `performance.now()` clock), `useMicLevel(mic: Pick<Mic, 'level'>): number | null`, `METER_MS = 50`
  - `Mic.level(): number | null` — RMS of the last 2048 samples while capturing, else null
  - `SentenceProps` with `pRef?: Ref<HTMLParagraphElement>`
  - `TopBar` props `chorusPasses: number`, `onHelp: () => void`

- [ ] **Step 1: Write the failing tests**

`frontend/src/components/KaraokeSentence.test.tsx`:
```tsx
import { cleanup, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import KaraokeSentence from './KaraokeSentence'

const words = [{ word: '你好', pinyin: 'nǐhǎo', tones: [3, 3], char_from: 0, char_to: 1, syllables: [] }]
const original = Range.prototype.getClientRects

describe('<KaraokeSentence>', () => {
  afterEach(() => { cleanup(); Range.prototype.getClientRects = original })

  it('keeps the sentence DOM Yomitan reads and draws the wipe on a separate inert layer', () => {
    // jsdom does no layout: give each character a 40 px box at 40 px × its offset in its text node
    Range.prototype.getClientRects = function (this: Range) {
      return [{ left: this.startOffset * 40, top: 0, width: 40, height: 40 }] as unknown as DOMRectList
    }
    const { container } = render(<KaraokeSentence text="你好。" words={words} showHanzi showPinyin wipe={{ tone: 'ref', progress: 1.5 }} />)
    const p = container.querySelector('p.sentence')!
    expect(p.getAttribute('lang')).toBe('zh')
    expect(p.querySelectorAll('ruby').length).toBe(1)
    expect(p.querySelectorAll('span, div').length).toBe(0)          // no per-character elements in the sentence
    const layer = container.querySelector('[data-testid="wipe"]') as HTMLElement
    expect(layer.getAttribute('aria-hidden')).toBe('true')
    expect(layer.className).toContain('pointer-events-none')
    expect(p.contains(layer)).toBe(false)
    const boxes = [...layer.children] as HTMLElement[]
    expect(boxes.map((b) => [b.style.left, b.style.width])).toEqual([['0px', '40px'], ['40px', '20px']]) // 你 full, 好 half
  })

  it('draws nothing without a wipe, or when the browser gives no character boxes', () => {
    const { container, rerender } = render(<KaraokeSentence text="你好" words={words} showHanzi showPinyin wipe={null} />)
    expect(container.querySelector('[data-testid="wipe"]')).toBeNull()
    rerender(<KaraokeSentence text="你好" words={words} showHanzi showPinyin wipe={{ tone: 'ghost', progress: 2 }} />)
    expect(container.querySelector('[data-testid="wipe"]')!.children.length).toBe(0)
  })
})
```

`frontend/src/components/TopBar.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import TopBar from './TopBar'

describe('<TopBar>', () => {
  it('each mode tab explains the mode on hover, and ? opens the help', () => {
    const onHelp = vi.fn()
    render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <TopBar title="L" speaker="" idx={0} total={2} mode="echo" onMode={() => {}} elapsedS={0} chorusPasses={5} onHelp={onHelp} />
    </MemoryRouter>)
    expect(screen.getByRole('button', { name: 'Echo' })).toHaveAttribute('title', 'One sentence at a time: listen, then repeat it on your own. You hear the original and your take back to back.')
    expect(screen.getByRole('button', { name: 'Chorus' })).toHaveAttribute('title', 'Speak at the same time as the sentence, 5 times in a row. Only the last pass is recorded.')
    expect(screen.getByRole('button', { name: 'Flow' }).title).toMatch(/^Shadow a whole passage without stopping\./)
    expect(screen.getByRole('button', { name: 'Guided' }).title).toMatch(/^Four steps per sentence:/)
    screen.getByRole('button', { name: 'Help' }).click()
    expect(onHelp).toHaveBeenCalled()
  })
})
```

In `frontend/src/pages/Practice.test.tsx`, in the top-level `beforeEach` add `useSettings.setState({ helpSeen: true })` (the help would otherwise open on every render and switch the shortcuts off), and append inside `describe('<Practice>', …)`:
```tsx
  it('opens the help on the first visit only; Esc closes it and ? opens it again', async () => {
    useSettings.setState({ helpSeen: false })
    renderPractice()
    expect(await screen.findByRole('dialog', { name: 'How to practise' })).toBeInTheDocument()
    expect(useSettings.getState().helpSeen).toBe(true)
    press('Enter')                                   // page shortcuts are off while it is open
    await flush()
    expect(h.rec.start).not.toHaveBeenCalled()
    press('Escape')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    press('?')
    expect(await screen.findByRole('dialog', { name: 'How to practise' })).toBeInTheDocument()
    press('?')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('the cue line says what to do: ready, your turn with a moving mic meter, then done', async () => {
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    expect(screen.getByTestId('cue-line')).toHaveTextContent('Ready — Enter to start')
    press('Enter')
    await waitFor(() => expect(screen.getByTestId('cue-line')).toHaveTextContent('Your turn — speak now'))
    expect(await screen.findByRole('meter', { name: 'Microphone level' })).toBeInTheDocument()
    press('Enter'); await flush()
    await waitFor(() => expect(screen.getByTestId('cue-line')).toHaveTextContent('Done — → for the next sentence, Enter to try again'))
    await waitFor(() => expect(screen.queryByRole('meter', { name: 'Microphone level' })).toBeNull()) // next 50 ms poll
  })
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/components/KaraokeSentence.test.tsx src/components/TopBar.test.tsx src/pages/Practice.test.tsx`
Expected: FAIL — `./KaraokeSentence` cannot be resolved; no `title` on the tabs; no help dialog or cue line.

- [ ] **Step 3: Small building blocks**

`frontend/src/components/Sentence.tsx`: replace the `Props` line and the `<p lang="zh" …>` opening tag:
```tsx
import type { Ref } from 'react'
import type { Word } from '../api/types'
import { fontSizeClass, sentenceRuns } from '../lib/sentence'

export interface SentenceProps {
  text: string; words: Word[] | null | undefined; showPinyin: boolean; showHanzi: boolean; translation?: string | null; showTranslation?: boolean
  pRef?: Ref<HTMLParagraphElement>  // the karaoke overlay measures the characters through it
}

export default function Sentence({ text, words, showPinyin, showHanzi, translation, showTranslation, pRef }: SentenceProps) {
  return (
    <div className="text-center">
      {showHanzi ? (
        <p ref={pRef} lang="zh" className={`sentence ${fontSizeClass(text.length)} ${showPinyin ? '' : 'hide-pinyin'}`}>
```
(the rest of the component is unchanged).

`frontend/src/audio/useMic.ts`: add `import { rms } from './pcm'`; add to the `Mic` interface
```ts
  // RMS of the last 2048 samples while capturing (the level meter, addendum §6.3), else null.
  level(): number | null
```
and to the object built in `useState` (after `now`):
```ts
    level: () => (capturing.current && recRef.current ? rms(recRef.current.tail(2048)) : null),
```

`frontend/src/audio/useMicLevel.ts`:
```ts
import { useEffect, useState } from 'react'
import type { Mic } from './useMic'

export const METER_MS = 50 // ~20 updates per second (addendum §6.3)

// The microphone level while it is open, else null. Re-renders only when the value changes.
export function useMicLevel(mic: Pick<Mic, 'level'>): number | null {
  const [level, setLevel] = useState<number | null>(null)
  useEffect(() => {
    const t = window.setInterval(() => { const v = mic.level(); setLevel((p) => (p === v ? p : v)) }, METER_MS)
    return () => window.clearInterval(t)
  }, [mic])
  return level
}
```

`frontend/src/lib/useNow.ts`:
```ts
import { useEffect, useState } from 'react'

const frame = (cb: () => void): number => (typeof requestAnimationFrame === 'function' ? requestAnimationFrame(cb) : window.setTimeout(cb, 16))
const cancelFrame = (id: number) => { if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(id); else window.clearTimeout(id) }

// performance.now() in seconds, refreshed every animation frame while `active` (count-in dots, ghost wipe, turn bar).
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => performance.now() / 1000)
  useEffect(() => {
    if (!active) return
    let id = 0
    const tick = () => { setNow(performance.now() / 1000); id = frame(tick) }
    id = frame(tick)
    return () => cancelFrame(id)
  }, [active])
  return now
}
```

`frontend/src/lib/charRects.ts`:
```ts
export interface Rect { left: number; top: number; width: number; height: number }

// Per character (code point) of the sentence's visible text — ruby base text and plain text, never <rt> pinyin — its
// first client rectangle relative to `container`, or null where the browser gives none. Same order as charFill().
export function charRects(p: HTMLElement, container: HTMLElement): (Rect | null)[] {
  const base = container.getBoundingClientRect()
  const out: (Rect | null)[] = []
  const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.parentElement?.closest('rt') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  })
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    let off = 0
    for (const ch of node.textContent ?? '') {
      const range = document.createRange()
      range.setStart(node, off); range.setEnd(node, off + ch.length)
      const r = typeof range.getClientRects === 'function' ? range.getClientRects()[0] : undefined
      out.push(r ? { left: r.left - base.left, top: r.top - base.top, width: r.width, height: r.height } : null)
      off += ch.length
    }
  }
  return out
}
```

- [ ] **Step 4: The components**

`frontend/src/components/CueLine.tsx`:
```tsx
import type { Cue, CueTone } from '../lib/cue'

const TONE: Record<CueTone, string> = { ref: 'text-ref', you: 'text-you', neutral: 'text-fgdim', ok: 'text-ok', bad: 'text-bad' }

// The current instruction (addendum §6.2), the count-in dots (§6.5) and, while the mic is open, its level (§6.3).
export default function CueLine({ cue, level, dots = 0 }: { cue: Cue; level: number | null; dots?: number }) {
  return (
    <div data-testid="cue-line" className="flex items-center justify-center gap-3 min-h-[2.5rem]">
      <span role="status" className={`text-2xl font-medium ${TONE[cue.tone]}`}><span aria-hidden="true">{cue.icon}</span> {cue.text}</span>
      {dots > 0 && <span aria-label={`starting in ${dots}`} className="text-you tracking-widest text-xl">{Array.from({ length: dots }, () => '●').join(' ')}</span>}
      {level != null && <MicMeter level={level} />}
    </div>
  )
}

export function MicMeter({ level }: { level: number }) {
  const v = Math.min(1, level * 3)
  return (
    <span role="meter" aria-label="Microphone level" aria-valuemin={0} aria-valuemax={1} aria-valuenow={v}
      className="inline-block w-24 h-2 bg-panel2 rounded overflow-hidden">
      <span className="block h-full bg-you" style={{ width: `${v * 100}%` }} />
    </span>
  )
}
```

`frontend/src/components/KaraokeSentence.tsx`:
```tsx
import { useLayoutEffect, useRef, useState } from 'react'
import { charRects, type Rect } from '../lib/charRects'
import { charFill, type Wipe } from '../lib/karaoke'
import Sentence, { type SentenceProps } from './Sentence'

const FILL: Record<Wipe['tone'], string> = { ref: '#8fb3d9', ghost: 'rgba(224, 163, 58, 0.55)' }

// The sentence with the karaoke wipe (addendum §6.5). The sentence DOM is Sentence's, unchanged (main spec §7.7); the
// wipe is a sibling layer — aria-hidden, pointer-events none — of boxes over each character's rectangle, multiplied
// into the light glyphs (and invisible on the dark background), so Yomitan still scans the real text underneath.
export default function KaraokeSentence({ wipe, ...props }: SentenceProps & { wipe: Wipe | null }) {
  const pRef = useRef<HTMLParagraphElement>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const [rects, setRects] = useState<(Rect | null)[]>([])
  const { text, words, showHanzi, showPinyin } = props
  useLayoutEffect(() => {
    const p = pRef.current, box = boxRef.current
    if (!p || !box) { setRects([]); return }
    const measure = () => setRects(charRects(p, box))
    measure()
    if (typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver(measure)
    ro.observe(p)
    return () => ro.disconnect()
  }, [text, words, showHanzi, showPinyin])
  const fill = wipe ? charFill(text, wipe.progress) : []
  return (
    <div ref={boxRef} className="relative">
      <Sentence {...props} pRef={pRef} />
      {wipe && showHanzi && (
        <div aria-hidden="true" data-testid="wipe" className="absolute inset-0 pointer-events-none" style={{ mixBlendMode: 'multiply' }}>
          {rects.map((r, i) => (r && fill[i] > 0
            ? <div key={i} className="absolute" style={{ left: r.left, top: r.top, width: r.width * fill[i], height: r.height, background: FILL[wipe.tone] }} />
            : null))}
        </div>)}
    </div>
  )
}

// With the text hidden: one blank cell per speech character, filled at the wipe's pace (no text is revealed).
export function GhostLine({ count, wipe }: { count: number; wipe: Wipe | null }) {
  if (!count) return null
  return (
    <div aria-hidden="true" data-testid="ghost-line" className="flex justify-center flex-wrap gap-1 mt-2">
      {Array.from({ length: count }, (_, i) => {
        const f = wipe ? Math.max(0, Math.min(1, wipe.progress - i)) : 0
        return (
          <span key={i} className="w-4 h-4 rounded-sm bg-panel2 overflow-hidden">
            <span className={`block h-full ${wipe?.tone === 'ghost' ? 'bg-you/60' : 'bg-ref'}`} style={{ width: `${f * 100}%` }} />
          </span>)
      })}
    </div>
  )
}
```

`frontend/src/components/HelpOverlay.tsx`:
```tsx
import { useEffect } from 'react'
import { KEY_HELP, MODES, modeHelp, modeName } from '../lib/modeHelp'

// The four modes and the key map (addendum §6.4). Esc or ? closes it.
export default function HelpOverlay({ chorusPasses, onClose }: { chorusPasses: number; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' || e.key === '?') { e.preventDefault(); onClose() } }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="help-title" className="bg-panel border border-line rounded p-6 w-[640px] max-h-[90vh] overflow-y-auto space-y-4"
        onClick={(e) => e.stopPropagation()}>
        <h2 id="help-title" className="text-fghi text-lg">How to practise</h2>
        <dl className="space-y-2 text-sm">{MODES.map((m) => (
          <div key={m}><dt className="text-fghi">{modeName(m)}</dt><dd className="text-fgdim">{modeHelp(m, chorusPasses)}</dd></div>))}</dl>
        <h3 className="text-fghi">Keys</h3>
        <table className="text-sm"><tbody>{KEY_HELP.map(([k, what]) => (
          <tr key={k}><td className="pr-4 text-fghi font-mono whitespace-pre">{k}</td><td className="text-fgdim">{what}</td></tr>))}</tbody></table>
        <div className="text-right"><button className="btn" onClick={onClose} autoFocus>Got it (Esc)</button></div>
      </div>
    </div>
  )
}
```

Replace `frontend/src/components/TopBar.tsx` with:
```tsx
import { Link } from 'react-router-dom'
import type { Mode } from '../api/types'
import { MODES, modeHelp, modeName } from '../lib/modeHelp'

export interface PassagePick { index: number; titles: string[]; onPick: (k: number) => void }
interface Props {
  title: string; speaker: string; idx: number; total: number; mode: Mode; onMode: (m: Mode) => void; elapsedS: number
  passage?: PassagePick | null; chorusPasses: number; onHelp: () => void
}
export default function TopBar({ title, speaker, idx, total, mode, onMode, elapsedS, passage, chorusPasses, onHelp }: Props) {
  const mm = String(Math.floor(elapsedS / 60)).padStart(2, '0'), ss = String(Math.floor(elapsedS % 60)).padStart(2, '0')
  return (
    <div className="flex items-center justify-between px-4 py-2 border-b border-line text-sm text-fgdim">
      <span><Link to="/library" className="mr-3 hover:text-fghi" title="Back to the library">←</Link>
        <span className="font-hanzi text-fghi">{speaker && `${speaker} · `}{title}</span> &nbsp; {idx + 1} / {total}
        {passage && passage.titles.length > 0 && (
          <label className="ml-3">Passage {Math.max(0, passage.index) + 1} / {passage.titles.length}
            <select aria-label="Go to passage" className="ml-1 bg-panel2 rounded px-1 py-0.5 text-fg" value={Math.max(0, passage.index)}
              onChange={(e) => passage.onPick(Number(e.target.value))}>
              {passage.titles.map((t, k) => <option key={k} value={k}>{t}</option>)}
            </select></label>)}</span>
      <span className="flex gap-1">{MODES.map((m) => (
        <button key={m} title={modeHelp(m, chorusPasses)} onClick={() => onMode(m)}
          className={`px-2 py-0.5 rounded border ${m === mode ? 'bg-[#1c2a3a] border-accent text-white' : 'border-line'}`}>{modeName(m)}</button>))}
        <button className="ml-2 px-2 py-0.5 rounded border border-line" aria-label="Help" title="Help (?)" onClick={onHelp}>?</button></span>
      <span className={elapsedS >= 1200 ? 'text-warn' : ''} title="Session time">⏱ {mm}:{ss}</span>
    </div>
  )
}
```

- [ ] **Step 5: Wire them into Practice**

`frontend/src/pages/Practice.tsx`:
- imports: delete `import Sentence from '../components/Sentence'`; add
```tsx
import { useMicLevel } from '../audio/useMicLevel'
import CueLine from '../components/CueLine'
import HelpOverlay from '../components/HelpOverlay'
import KaraokeSentence, { GhostLine } from '../components/KaraokeSentence'
import { cueFor, cuePhase } from '../lib/cue'
import { clipSpans, stageWipe } from '../lib/karaoke'
import { useNow } from '../lib/useNow'
```
- right after `const flow = useFlow({ … })` add:
```tsx
  const [echoTurn, setEchoTurn] = useState<number | null>(null) // performance-clock second an Echo take began (count-in, ghost wipe)
  const [help, setHelp] = useState(() => !useSettings.getState().helpSeen)
  const helpOpen = useRef(false)
  helpOpen.current = help
  const level = useMicLevel(mic)
  const now = useNow(echoTurn != null)
```
- after the elapsed-timer effect add:
```tsx
  // The help opens by itself once, on the first visit to a practice page (addendum §6.4).
  useEffect(() => { if (!useSettings.getState().helpSeen) useSettings.getState().set({ helpSeen: true }) }, [])
  // An Echo take's count-in and ghost wipe last while it records.
  useEffect(() => { if (echo !== 'recording') setEchoTurn(null) }, [echo])
```
- in `startRecording` replace `      if (!rec) return` with
```tsx
      if (!rec) return
      if (mode === 'echo') setEchoTurn(performance.now() / 1000)
```
- in `act` right after `if (ps.lesson?.id !== lessonId) return // …` add `if (a === 'help') { setHelp(true); return }`;
- in the keydown effect replace `if (dialogOpen.current) return // …` with `if (dialogOpen.current || helpOpen.current) return // a dialog or the help keeps its own keys`;
- after `const volume: VolumeControls = { … }` add:
```tsx
  const spans = clipSpans(seg.ref_alignment_json, seg.start_s)
  const refPlaying = echo === 'playing' || echo === 'playback' || runKind === 'chorus' || runKind === 'guided'
  const { wipe, dots } = stageWipe({ spans, refPlaying, refHead, turnStart: st.mode === 'echo' ? echoTurn : null, now, rate: st.rate })
  const cue = cueFor(st.mode, {
    phase: cuePhase({ mode: st.mode, echo, runKind, guided, hasTake: st.lastAttempt != null, flowPhase: fs.phase, flowSub: fs.sub, flowTurn: false }),
    guided, error: !!error,
  })
```
- in the JSX replace `            <div className="flex-1 overflow-y-auto p-6 space-y-6">` with
```tsx
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              <CueLine cue={cue} level={level} dots={dots} />
```
  and replace the `<Sentence … />` line with
```tsx
                <KaraokeSentence wipe={wipe} text={seg.text} words={seg.words_json} showHanzi={st.textPrefs.hanzi && show} showPinyin={st.textPrefs.pinyin && show} translation={seg.translation} showTranslation={st.textPrefs.translation && show} />
                {!(st.textPrefs.hanzi && show) && wipe && <GhostLine count={spans.length} wipe={wipe} />}
```
- add `chorusPasses={settings.practice.chorusPasses} onHelp={() => setHelp(true)}` to `<TopBar … />`;
- just before the final closing `</div>` of the page add:
```tsx
      {help && <HelpOverlay chorusPasses={settings.practice.chorusPasses} onClose={() => setHelp(false)} />}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run && npx eslint src`
Expected: PASS; no eslint errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/CueLine.tsx frontend/src/components/KaraokeSentence.tsx frontend/src/components/KaraokeSentence.test.tsx frontend/src/components/HelpOverlay.tsx frontend/src/components/TopBar.tsx frontend/src/components/TopBar.test.tsx frontend/src/components/Sentence.tsx frontend/src/lib/charRects.ts frontend/src/lib/useNow.ts frontend/src/audio/useMicLevel.ts frontend/src/audio/useMic.ts frontend/src/pages/Practice.tsx frontend/src/pages/Practice.test.tsx
git commit -m "feat(frontend): cue line, mic meter, karaoke wipe, help overlay and mode tooltips"
```

---

### Task 14: Frontend — Flow karaoke: wipe, ghost wipe, count-in, next line, turn bar

**Files:**
- Modify: `frontend/src/lib/flowRun.ts`, `frontend/src/lib/flowRun.test.ts`, `frontend/src/pages/useFlow.ts`, `frontend/src/components/FlowView.tsx` (replace the whole file), `frontend/src/pages/Practice.tsx`, `frontend/src/pages/Practice.test.tsx`
- Create: `frontend/src/components/FlowView.test.tsx`

**Interfaces:**
- Consumes: Task 11 (`flowWipe`, `nextLineStart`, `clipSpans`, `Cue`), Task 13 (`CueLine`, `KaraokeSentence`, `GhostLine`, `useNow`, `useMicLevel`), Task 12 (`FlowTransport` with volume and hint).
- Produces:
  - `PlayFlowOptions.onTime?: (t: number) => void` (clip-relative time of the sentence playing); `PlayFlowOptions.onTurn?: (clip: FlowClip, turn: { duration: number } | null) => void` (`after`: the speaking window opens with its length in seconds, `gapAfter(refDuration, gapFactor)`, and closes with null)
  - `FlowState.clipTime: number | null`, `FlowState.turn: { startedAt: number; duration: number } | null` (`startedAt` on the `performance.now()/1000` clock); `FlowState.micPeak` removed (the cue line's meter replaces it)
  - `FlowView` props `{ segments, current, pending, sub, showText, cue: Cue, level: number | null, rate: number, now: number, clipTime, turn }` (no `micPeak`); test ids `turn-bar`, `next-line`

- [ ] **Step 1: Write the failing tests**

Append to `frontend/src/lib/flowRun.test.ts` inside `describe('playFlow', …)`:
```ts
  it('after: opens the speaking window when a clip ends and closes it before the next clip', async () => {
    const turns: (number | null)[] = []
    const run = playFlow({ player, clock: () => clock, clips, sub: 'after', gapFactor: 1.1, rate: () => 1, signal: new AbortController().signal,
      onClip: () => {}, onTurn: (_c, t) => { turns.push(t && t.duration) } })
    await vi.advanceTimersByTimeAsync(0)
    await finishClip(2)
    expect(turns).toEqual([2.2])
    await vi.advanceTimersByTimeAsync(2600)
    expect(turns).toEqual([2.2, null])
    await finishClip(1)
    await vi.advanceTimersByTimeAsync(1500)
    await run
    expect(turns).toEqual([2.2, null, 1.1, null])
  })

  it('passes the clip-time callback to the player', async () => {
    const onTime = vi.fn()
    const run = playFlow({ player, clock: () => clock, clips: clips.slice(0, 1), sub: 'along', gapFactor: 1.1, rate: () => 1,
      signal: new AbortController().signal, onClip: () => {}, onTime })
    await vi.advanceTimersByTimeAsync(0)
    expect(player.play).toHaveBeenCalledWith('/1', 1, onTime)
    await finishClip(2)
    await run
  })
```

`frontend/src/components/FlowView.test.tsx`:
```tsx
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Segment } from '../api/types'
import FlowView from './FlowView'

const seg = (id: number, idx: number, text: string, start: number): Segment => ({
  id, lesson_id: 1, idx, start_s: start, end_s: start + 2, text, translation: null, words_json: null,
  ref_alignment_json: [{ ch: text[0], start: start + 0.1, end: start + 1.0, conf: 1 }, { ch: text[1], start: start + 1.0, end: start + 1.9, conf: 1 }],
  difficulty_flag: false, anki_note_id: null, last_score: null, best_score: null, attempts: 0,
})
const base = {
  segments: [seg(1, 0, '你好', 0), seg(2, 1, '再见', 2), seg(3, 2, '谢谢', 4)], current: 0, pending: new Set<number>(), rate: 1, now: 100,
  level: 0.1, cue: { icon: '🎧', text: 'Listen', tone: 'ref' as const }, clipTime: null, turn: null,
}

describe('<FlowView>', () => {
  it('shows the cue with the mic meter, the current line large and the next line dimmed below it', () => {
    render(<FlowView {...base} sub="along" showText />)
    expect(screen.getByTestId('cue-line')).toHaveTextContent('Listen')
    expect(screen.getByRole('meter', { name: 'Microphone level' })).toBeInTheDocument()
    expect(screen.getByText('你好', { selector: 'p.sentence' })).toBeInTheDocument()
    expect(screen.getByTestId('next-line')).toHaveTextContent('再见')
    expect(screen.getByTestId('next-line').className).toContain('text-fgdim')
  })
  it('after, during the turn: the turn bar shrinks and the ghost line fills at the reference pace', () => {
    render(<FlowView {...base} sub="after" showText={false} now={101} turn={{ startedAt: 99, duration: 4 }} />)
    expect((screen.getByTestId('turn-bar').firstChild as HTMLElement).style.width).toBe('50%')
    const cells = screen.getByTestId('ghost-line').querySelectorAll('span > span')
    expect([...cells].map((c) => (c as HTMLElement).style.width)).toEqual(['100%', '100%'])
  })
  it('after: count-in dots over the last 1.5 s of the clip', () => {
    render(<FlowView {...base} sub="after" showText clipTime={1.0} />)
    expect(screen.getByLabelText('starting in 2')).toBeInTheDocument()
    expect(screen.queryByTestId('turn-bar')).toBeNull()
  })
})
```

In `frontend/src/pages/Practice.test.tsx`, inside `describe('Flow', …)`:
```tsx
    it('after: the cue line says your turn during the pause, with the turn bar', async () => {
      clipsTake(2)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('after')
      await waitFor(() => expect(screen.getByTestId('cue-line')).toHaveTextContent('Your turn — speak now'))
      expect(screen.getByTestId('turn-bar')).toBeInTheDocument()
      press('Enter')
      expect(await screen.findByText(/Flow finished/)).toBeInTheDocument()
    })
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/lib/flowRun.test.ts src/components/FlowView.test.tsx src/pages/Practice.test.tsx`
Expected: FAIL — `onTurn` never called; FlowView has no cue line / turn bar / next-line.

- [ ] **Step 3: playFlow callbacks**

In `frontend/src/lib/flowRun.ts` add to `PlayFlowOptions`:
```ts
  onTime?: (t: number) => void                                          // clip-relative time of the sentence playing (karaoke)
  onTurn?: (clip: FlowClip, turn: { duration: number } | null) => void // after: the speaking window opens (its length) / closes
```
replace `      await playClip(o.player, c.url, rate, skip.signal)` with `      await playClip(o.player, c.url, rate, skip.signal, o.onTime)`, and replace the `after` block
```ts
      if (o.sub === 'after') {
        await sleep(gapAfter(a.refDuration, o.gapFactor) * 1000 + AFTER_PAUSE_MS, skip.signal)
```
with
```ts
      if (o.sub === 'after') {
        o.onTurn?.(c, { duration: gapAfter(a.refDuration, o.gapFactor) })
        await sleep(gapAfter(a.refDuration, o.gapFactor) * 1000 + AFTER_PAUSE_MS, skip.signal)
        o.onTurn?.(c, null)
```

- [ ] **Step 4: useFlow state**

In `frontend/src/pages/useFlow.ts`:
- change `import { rms, sliceSamples } from '../audio/pcm'` to `import { sliceSamples } from '../audio/pcm'`;
- in `FlowState` replace `current: number; micPeak: number` with
```ts
  current: number
  clipTime: number | null                                   // clip-relative time of the sentence playing (karaoke)
  turn: { startedAt: number; duration: number } | null      // after: the open speaking window, on the performance.now()/1000 clock
```
- in `initial` replace `current: 0, micPeak: 0,` with `current: 0, clipTime: null, turn: null,`;
- in `start` replace `current: from, micPeak: 0 }))` with `current: from, clipTime: null, turn: null }))`, replace `setState((f) => ({ ...f, phase: 'setup', micPeak: 0 }))` with `setState((f) => ({ ...f, phase: 'setup', clipTime: null, turn: null }))`, and in the summary `setState` replace `phase: 'summary', micPeak: 0,` with `phase: 'summary', clipTime: null, turn: null,`;
- in `record` delete the line `let meter: number | undefined`, the lines `const r = rec` and `meter = window.setInterval(…)`, and `clearInterval(meter)` in the `finally`; replace the `onClip` option with
```ts
        onClip: (c, skip) => { skipCtrl.current = skip; mine(() => setState((f) => ({ ...f, current: c.idx, clipTime: 0, turn: null }))) },
        onTime: (t) => mine(() => setState((f) => ({ ...f, clipTime: t }))),
        onTurn: (_c, t) => mine(() => setState((f) => ({ ...f, turn: t && { startedAt: performance.now() / 1000, duration: t.duration } }))),
```

- [ ] **Step 5: FlowView**

Replace `frontend/src/components/FlowView.tsx` with:
```tsx
import { useEffect, useRef } from 'react'
import type { Segment } from '../api/types'
import type { Cue } from '../lib/cue'
import type { FlowSub } from '../lib/flow'
import { clipSpans, flowWipe, nextLineStart } from '../lib/karaoke'
import CueLine from './CueLine'
import { dotClass } from './Drawer'
import KaraokeSentence, { GhostLine } from './KaraokeSentence'
import VolumeSliders, { type VolumeControls } from './VolumeSliders'

export interface FlowViewProps {
  segments: Segment[]; current: number; pending: Set<number>; sub: FlowSub; showText: boolean
  cue: Cue; level: number | null; rate: number; now: number
  clipTime: number | null; turn: { startedAt: number; duration: number } | null
}

// Flow mode while running (main spec §7.3, addendum §6.5): the lesson as a transcript; the current line large with
// the cue line, count-in, karaoke wipe (in after: ghost wipe and turn bar during the learner's turn); the next line
// dimmed right below it.
export default function FlowView(p: FlowViewProps) {
  const curRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => { curRef.current?.scrollIntoView?.({ block: 'center', behavior: 'smooth' }) }, [p.current])
  const cur = p.segments[p.current], next = p.segments[p.current + 1]
  const spans = cur ? clipSpans(cur.ref_alignment_json, cur.start_s) : []
  const k = cur
    ? flowWipe({ spans, sub: p.sub, clipTime: p.clipTime, clipDuration: cur.end_s - cur.start_s, turn: p.turn, now: p.now, rate: p.rate,
      next: p.sub === 'along' && next ? nextLineStart(cur, next, p.rate) : null })
    : { wipe: null, dots: 0, turnLeft: null }
  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-1">
      {p.segments.map((s, i) => {
        const isCur = i === p.current, isNext = i === p.current + 1
        return (
          <div key={s.id} ref={isCur ? curRef : undefined} className={`flex gap-3 items-start px-3 py-1 rounded ${isCur ? 'bg-[#1c2a3a] py-3' : ''}`}>
            <span className="w-6 text-right text-[10px] text-fgdim pt-1">{s.idx + 1}</span>
            <span className={`w-2 h-2 mt-2 rounded-full flex-none ${dotClass(s, p.pending.has(s.id))}`} />
            {isCur ? (
              <div className="flex-1 space-y-2">
                <CueLine cue={p.cue} level={p.level} dots={k.dots} />
                <KaraokeSentence wipe={k.wipe} text={s.text} words={s.words_json} showHanzi={p.showText} showPinyin={p.showText} />
                {!p.showText && <GhostLine count={spans.length} wipe={k.wipe} />}
                {k.turnLeft != null && (
                  <div data-testid="turn-bar" className="h-1 bg-panel2 rounded overflow-hidden"><div className="h-full bg-you" style={{ width: `${k.turnLeft * 100}%` }} /></div>)}
              </div>
            ) : (
              <span data-testid={isNext ? 'next-line' : undefined}
                className={`font-hanzi truncate ${i < p.current ? 'text-fgdim' : isNext ? 'text-fgdim text-lg' : 'text-fg text-sm'}`}>{s.text}</span>)}
          </div>)
      })}
    </div>
  )
}

// Flow mode before a run: which sentences, which sub-mode.
export function FlowSetup({ segments, from, to, sub, onChange, onStart }: { segments: Segment[]; from: number; to: number; sub: FlowSub; onChange: (p: { from?: number; to?: number; sub?: FlowSub }) => void; onStart: () => void }) {
  const pick = (label: string, value: number, key: 'from' | 'to') => (
    <select aria-label={label} className="bg-panel2 rounded px-1 py-0.5 text-fg" value={value} onChange={(e) => onChange({ [key]: Number(e.target.value) })}>
      {segments.map((s, i) => <option key={s.id} value={i}>{i + 1}. {s.text.length > 12 ? `${s.text.slice(0, 12)}…` : s.text}</option>)}
    </select>)
  const tab = (v: FlowSub) => <button aria-pressed={sub === v} className={`px-2 py-0.5 rounded border ${sub === v ? 'bg-[#1c2a3a] border-accent text-white' : 'border-line'}`} onClick={() => onChange({ sub: v })}>{v}</button>
  return (
    <div className="flex items-center justify-center gap-2 text-sm text-fgdim">
      Flow from {pick('Flow from', from, 'from')} to {pick('Flow to', to, 'to')} {tab('after')}{tab('along')}
      <button className="btn" onClick={onStart}>Start</button>
    </div>
  )
}

// Flow mode while running: ■ stop (Enter) · skip (→) · speed · volume. Pause is not in v1.
export function FlowTransport({ rate, onRate, sub, onStop, onSkip, error, hint, volume }: {
  rate: number; onRate: (r: number) => void; sub: FlowSub; onStop: () => void; onSkip: () => void; error: string; hint: string; volume: VolumeControls
}) {
  const b = 'px-3 py-1 rounded bg-panel2 text-sm'
  return (
    <div className="border-t border-line p-3 text-center space-y-1">
      <div className="flex justify-center gap-2 items-center">
        <button className={`${b} bg-[#5a1f26] text-[#ffd7db]`} onClick={onStop} title="Stop and save the finished sentences (Enter)">■ stop</button>
        <button className={b} onClick={onSkip} title="Skip this sentence (→)">skip ▸▸</button>
        <label className="text-xs text-fgdim flex items-center gap-1">{rate.toFixed(2)}×<input type="range" aria-label="Playback speed" min={0.6} max={1} step={0.05} value={rate}
          onChange={(e) => onRate(Number(e.target.value))} onPointerUp={(e) => e.currentTarget.blur()} /></label>
        <button className={b} onClick={() => onRate(rate === 0.75 ? 1 : 0.75)}>0.75×</button>
        <span className="text-xs text-fgdim">{sub}</span>
        <VolumeSliders volume={volume} />
      </div>
      {hint && <p className="text-xs text-warn">{hint}</p>}
      {error && <p className="text-xs text-bad" role="alert">{error}</p>}
    </div>
  )
}
```

- [ ] **Step 6: Practice**

In `frontend/src/pages/Practice.tsx`:
- replace `const now = useNow(echoTurn != null)` with `const now = useNow(echoTurn != null || flow.state.turn != null)`;
- in the `cuePhase({ … })` call replace `flowTurn: false` with `flowTurn: fs.turn != null`;
- replace the `<FlowView … />` element with:
```tsx
            <FlowView segments={segments} current={fs.current} pending={fs.pending} sub={fs.sub} rate={st.rate} now={now}
              cue={cue} level={level} clipTime={fs.clipTime} turn={fs.turn}
              showText={!(settings.practice.hideTextWhileRecording && fs.sub === 'after')} />
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run && npx eslint src`
Expected: PASS; no eslint errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/flowRun.ts frontend/src/lib/flowRun.test.ts frontend/src/pages/useFlow.ts frontend/src/components/FlowView.tsx frontend/src/components/FlowView.test.tsx frontend/src/pages/Practice.tsx frontend/src/pages/Practice.test.tsx
git commit -m "feat(frontend): Flow karaoke wipe, ghost wipe, count-in, next line and turn bar"
```

---
### Task 15: Backend — `GET /review/unexported` (practised, not in Anki)

**Files:**
- Create: `backend/shadow/api/review.py`
- Modify: `backend/shadow/main.py` (register the router)
- Test: `backend/tests/test_review_api.py`

**Interfaces:**
- Consumes: `_segment_out(db, seg) -> SegmentOut` from `shadow.api.lessons`.
- Produces: `GET /review/unexported` → `[{lesson_id: int, lesson_title: str, lesson_source_type: str, lesson_source_ref: str, last_attempt_at: datetime, segment: SegmentOut}]` — segments with at least one attempt (any mode) and no `anki_note_id`, newest last attempt first.

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_review_api.py`:
```python
from datetime import datetime, timedelta, timezone
from sqlmodel import Session
from shadow.store.models import Attempt, Segment
from tests.test_lessons_api import _upload


def test_unexported_lists_practised_sentences_without_a_note_newest_first(client, tmp_path):
    lid = _upload(client, tmp_path, "L")
    segs = client.get(f"/lessons/{lid}").json()["segments"]
    t0 = datetime(2026, 10, 7, 9, 0, tzinfo=timezone.utc)
    with Session(client.app.state.engine) as db:
        for sid, minutes in ((segs[0]["id"], 0), (segs[0]["id"], 5), (segs[2]["id"], 3), (segs[1]["id"], 9)):
            db.add(Attempt(segment_id=sid, mode="flow", audio_path="x.wav", duration_s=1.0, created_at=t0 + timedelta(minutes=minutes)))
        sent = db.get(Segment, segs[1]["id"])
        sent.anki_note_id = 77                                   # in Anki: never listed, however recent
        db.add(sent)
        db.commit()
    out = client.get("/review/unexported").json()
    assert [r["segment"]["id"] for r in out] == [segs[0]["id"], segs[2]["id"]]     # last attempts 09:05, 09:03
    first = out[0]
    assert (first["lesson_id"], first["lesson_title"], first["lesson_source_type"]) == (lid, "L", "upload")
    assert first["segment"]["attempts"] == 2 and first["last_attempt_at"].startswith("2026-10-07T09:05")


def test_unexported_is_empty_without_attempts(client, tmp_path):
    _upload(client, tmp_path)
    assert client.get("/review/unexported").json() == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_review_api.py -q`
Expected: FAIL — 404 for `/review/unexported`.

- [ ] **Step 3: Implement**

`backend/shadow/api/review.py`:
```python
from __future__ import annotations
from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlmodel import Session, select
from shadow.api.lessons import _segment_out
from shadow.schemas import SegmentOut
from shadow.store.db import get_session
from shadow.store.models import Attempt, Lesson, Segment

router = APIRouter()


class UnexportedOut(BaseModel):
    lesson_id: int
    lesson_title: str
    lesson_source_type: str
    lesson_source_ref: str
    last_attempt_at: datetime
    segment: SegmentOut


@router.get("/review/unexported", response_model=list[UnexportedOut])
def unexported(db: Session = Depends(get_session)):
    """Practised sentences (at least one attempt, any mode, Flow slices included) that have no Anki note, newest last
    attempt first (addendum §5.2): what a session-end export did not send, e.g. because Anki was closed."""
    last = func.max(Attempt.created_at)
    q = (select(Segment, last).join(Attempt, Attempt.segment_id == Segment.id)
         .where(Segment.anki_note_id.is_(None)).group_by(Segment.id).order_by(last.desc(), Segment.id.desc()))
    lessons: dict[int, Lesson] = {}
    out = []
    for seg, last_at in db.exec(q).all():
        lesson = lessons.setdefault(seg.lesson_id, db.get(Lesson, seg.lesson_id))
        out.append(UnexportedOut(lesson_id=lesson.id, lesson_title=lesson.title, lesson_source_type=lesson.source_type,
                                 lesson_source_ref=lesson.source_ref, last_attempt_at=last_at, segment=_segment_out(db, seg)))
    return out
```

`backend/shadow/main.py`: change the router import to `from shadow.api import anki, attempts, health, jobs, lessons, review, segments, sessions, stats` and add `review.router` to the tuple in the `for r in (...)` loop (before `segments.router`).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd backend && ~/.local/bin/uv run pytest tests/test_review_api.py -q && ~/.local/bin/uv run pytest -q`
Expected: PASS; the whole suite passes.

- [ ] **Step 5: Commit**

```bash
git add backend/shadow/api/review.py backend/shadow/main.py backend/tests/test_review_api.py
git commit -m "feat(backend): GET /review/unexported lists practised sentences not in Anki"
```

---

### Task 16: Frontend — the Shadow Listening note type and listening-card fields

**Files:**
- Create: `frontend/src/anki/listening.ts`, `frontend/src/anki/listening.test.ts`
- Modify: `frontend/src/anki/client.ts`, `frontend/src/anki/client.test.ts`, `frontend/src/anki/export.ts`, `frontend/src/anki/export.test.ts`, `frontend/src/store/settings.ts` (`ExportNote.fields`), `frontend/src/pages/Settings.tsx`, `frontend/src/pages/Settings.test.tsx` (replace the whole file), `frontend/src/pages/Practice.tsx` (`sendToAnki`), `frontend/src/pages/Practice.test.tsx` (one assertion), `frontend/src/pages/Review.tsx` (`sendAll`)

**Interfaces:**
- Consumes: AnkiConnect `deckNames`, `modelNames`, `modelFieldNames`, `createDeck {deck}`, `createModel {modelName, inOrderFields, css, isCloze, cardTemplates: [{Name, Front, Back}]}`.
- Produces (used by Tasks 17, 18):
  - `anki(url).createDeck(deck: string)`, `anki(url).createModel(m: NewModel)`, `export interface NewModel { modelName: string; inOrderFields: string[]; css: string; isCloze: boolean; cardTemplates: { Name: string; Front: string; Back: string }[] }`
  - `LISTENING_DECK = 'shadow-speech'`, `LISTENING_MODEL = 'Shadow Listening'`, `LISTENING_FIELDS`, `listeningModel: NewModel`, `setupListeningDeck(ankiUrl: string): Promise<{ deckCreated: boolean; modelCreated: boolean; exportNote: ExportNote }>`
  - `ExportNote.fields` gains `source?: string; link?: string`
  - `export interface LessonRef { id: number; title: string; source_type: string; source_ref: string }`, `mmss(s: number): string`, `sourceText(lesson: LessonRef, seg: Segment): string`, `youtubeLink(lesson: LessonRef, seg: Segment): string`
  - `buildExportNote(seg, mp3b64, cfg, allowDuplicate = false, lesson?: LessonRef)`, `exportToAnki(seg, ankiUrl, cfg, lesson?: LessonRef)`, `exportAndRecord(seg, ankiUrl, cfg, lesson?: LessonRef)`; tags are `['shadow', 'shadow::<lesson id>']`

- [ ] **Step 1: Write the failing tests**

`frontend/src/anki/listening.test.ts`:
```ts
import { afterEach, describe, expect, it, vi } from 'vitest'
import { LISTENING_DECK, LISTENING_MODEL, listeningModel, setupListeningDeck } from './listening'

const reply = (result: unknown, error: string | null = null) => new Response(JSON.stringify({ result, error }))
const bodies = (f: { mock: { calls: unknown[][] } }) => f.mock.calls.map((c) => JSON.parse((c[1] as RequestInit).body as string))

describe('setupListeningDeck', () => {
  afterEach(() => { vi.restoreAllMocks() })

  it('creates the deck and the note type when missing and maps every field', async () => {
    const f = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(reply(['Default'])).mockResolvedValueOnce(reply(1))
      .mockResolvedValueOnce(reply(['Basic'])).mockResolvedValueOnce(reply({}))
    const r = await setupListeningDeck('http://anki')
    const sent = bodies(f)
    expect(sent.map((b) => b.action)).toEqual(['deckNames', 'createDeck', 'modelNames', 'createModel'])
    expect(sent[1].params).toEqual({ deck: 'shadow-speech' })
    const model = sent[3].params
    expect(model).toEqual(listeningModel)
    expect(model.modelName).toBe('Shadow Listening')
    expect(model.inOrderFields).toEqual(['Audio', 'Sentence', 'Pinyin', 'Translation', 'Source', 'Link'])
    expect(model.cardTemplates[0].Front).toContain('{{Audio}}')
    expect(model.cardTemplates[0].Front).toContain('What did you hear?')
    expect(model.cardTemplates[0].Back).toMatch(/\{\{FrontSide\}\}[\s\S]*<hr[\s\S]*\{\{Sentence\}\}[\s\S]*\{\{Pinyin\}\}[\s\S]*\{\{Translation\}\}[\s\S]*<a href="\{\{Link\}\}">\{\{Source\}\}<\/a>/)
    expect(r).toEqual({ deckCreated: true, modelCreated: true, exportNote: { deckName: LISTENING_DECK, modelName: LISTENING_MODEL,
      fields: { sentence: 'Sentence', audio: 'Audio', pinyin: 'Pinyin', translation: 'Translation', source: 'Source', link: 'Link' } } })
  })

  it('reuses an existing deck and note type without changing them', async () => {
    const f = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(reply(['shadow-speech'])).mockResolvedValueOnce(reply(['Shadow Listening']))
      .mockResolvedValueOnce(reply(['Audio', 'Sentence', 'Source']))
    const r = await setupListeningDeck('http://anki')
    expect(bodies(f).map((b) => b.action)).toEqual(['deckNames', 'modelNames', 'modelFieldNames'])
    expect([r.deckCreated, r.modelCreated]).toEqual([false, false])
    expect(r.exportNote.fields).toEqual({ sentence: 'Sentence', audio: 'Audio', source: 'Source' })
  })

  it('refuses an existing note type without Sentence and Audio fields', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(reply(['shadow-speech'])).mockResolvedValueOnce(reply(['Shadow Listening']))
      .mockResolvedValueOnce(reply(['Front', 'Back']))
    await expect(setupListeningDeck('http://anki')).rejects.toThrow(/no Sentence or Audio field/)
  })

  it('passes AnkiConnect errors through', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(reply(['Default'])).mockResolvedValueOnce(reply(null, 'deck name is invalid'))
    await expect(setupListeningDeck('http://anki')).rejects.toThrow('deck name is invalid')
  })
})
```

Append to `frontend/src/anki/client.test.ts` inside its `describe`:
```ts
  it('creates a deck', async () => {
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ result: 1, error: null })))
    await anki('http://x').createDeck('shadow-speech')
    expect(JSON.parse(f.mock.calls[0][1]!.body as string)).toEqual({ action: 'createDeck', version: 6, params: { deck: 'shadow-speech' } })
  })
```

In `frontend/src/anki/export.test.ts`, in `'maps fields, pinyin and audio'` change `expect(n.tags).toEqual(['shadow'])` to `expect(n.tags).toEqual(['shadow', 'shadow::1'])`, and append:
```ts
describe('listening card fields', () => {
  afterEach(() => { vi.restoreAllMocks() })
  const full = { deckName: 'shadow-speech', modelName: 'Shadow Listening', fields: { sentence: 'Sentence', pinyin: 'Pinyin', translation: 'Translation', audio: 'Audio', source: 'Source', link: 'Link' } }
  const yt = { id: 7, title: '学中文', source_type: 'youtube', source_ref: 'youtube::abcDEF12345' }

  it('adds Source (title · mm:ss), the YouTube Link at that second, and the lesson tag', () => {
    const n = buildExportNote({ ...seg, lesson_id: 7, start_s: 83.6 }, 'QUJD', full, false, yt)
    expect(n.fields).toMatchObject({ Sentence: '你好。', Source: '学中文 · 01:23', Link: 'https://www.youtube.com/watch?v=abcDEF12345&t=83' })
    expect(n.tags).toEqual(['shadow', 'shadow::7'])
  })
  it('leaves Link out for lessons not from YouTube', () => {
    const n = buildExportNote(seg, 'QUJD', full, false, { id: 1, title: 'L', source_type: 'upload', source_ref: 'a.mp4' })
    expect(n.fields.Source).toBe('L · 00:00')
    expect(n.fields).not.toHaveProperty('Link')
  })
  it('exportAndRecord passes the lesson on to the note', async () => {
    const f = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('ABC'))
      .mockResolvedValueOnce(new Response(JSON.stringify({ result: 780, error: null })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...seg, anki_note_id: 780 })))
    await exportAndRecord(seg, 'http://anki', full, { id: 1, title: 'L', source_type: 'upload', source_ref: 'a.mp4' })
    expect(JSON.parse((f.mock.calls[1][1] as RequestInit).body as string).params.note.fields.Source).toBe('L · 00:00')
  })
})
```

Replace `frontend/src/pages/Settings.test.tsx` with:
```tsx
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useSettings } from '../store/settings'

const h = vi.hoisted(() => ({ setup: vi.fn() }))
vi.mock('../anki/listening', async (importOriginal) => ({ ...(await importOriginal<typeof import('../anki/listening')>()), setupListeningDeck: h.setup }))
import Settings from './Settings'

const exportNote = { deckName: 'shadow-speech', modelName: 'Shadow Listening',
  fields: { sentence: 'Sentence', audio: 'Audio', pinyin: 'Pinyin', translation: 'Translation', source: 'Source', link: 'Link' } }

describe('<Settings>', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); h.setup.mockReset(); useSettings.setState({ exportNote: null }) })

  it('offers the bookmarklet for this origin', () => {
    render(<Settings />)
    const link = screen.getByRole('link', { name: '→ shadow-speech' })
    expect(link.getAttribute('href')).toBe(`javascript:location.href='${window.location.origin}/library?add='+encodeURIComponent(location.href)`)
  })

  it('sets up the listening deck after confirming and uses it for export', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({ result: [], error: null })))
    h.setup.mockResolvedValue({ deckCreated: true, modelCreated: true, exportNote })
    render(<Settings />)
    fireEvent.click(screen.getByRole('button', { name: 'Set up shadow-speech deck' }))
    expect(await screen.findByText(/Created deck shadow-speech, created note type Shadow Listening/)).toBeInTheDocument()
    expect(h.setup).toHaveBeenCalledWith(useSettings.getState().ankiUrl)
    expect(useSettings.getState().exportNote).toEqual(exportNote)
  })

  it('does nothing unless confirmed', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<Settings />)
    fireEvent.click(screen.getByRole('button', { name: 'Set up shadow-speech deck' }))
    expect(h.setup).not.toHaveBeenCalled()
  })

  it('shows an AnkiConnect error verbatim after a short explanation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    h.setup.mockRejectedValue(new Error('collection is not available'))
    render(<Settings />)
    fireEvent.click(screen.getByRole('button', { name: 'Set up shadow-speech deck' }))
    expect(await screen.findByText('Could not set up the deck. AnkiConnect said: collection is not available')).toBeInTheDocument()
    expect(useSettings.getState().exportNote).toBeNull()
  })
})
```

In `frontend/src/pages/Practice.test.tsx` replace
```tsx
      expect(h.exportAndRecord).toHaveBeenCalledWith(expect.objectContaining({ id: 11 }), useSettings.getState().ankiUrl, cfg)
```
with
```tsx
      expect(h.exportAndRecord).toHaveBeenCalledWith(expect.objectContaining({ id: 11 }), useSettings.getState().ankiUrl, cfg, expect.objectContaining({ id: 1, title: 'Lesson' }))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/anki src/pages/Settings.test.tsx src/pages/Practice.test.tsx`
Expected: FAIL — `./listening` cannot be resolved; `createDeck` is not a function; tags lack `shadow::1`; no setup button; the Practice assertion misses the lesson.

- [ ] **Step 3: AnkiConnect client, settings type, listening note type**

`frontend/src/anki/client.ts`: add
```ts
export interface NewModel { modelName: string; inOrderFields: string[]; css: string; isCloze: boolean; cardTemplates: { Name: string; Front: string; Back: string }[] }
```
and in the object returned by `anki(url)`:
```ts
  createDeck: (deck: string) => ankiRequest<number>(url, 'createDeck', { deck }),
  createModel: (m: NewModel) => ankiRequest<unknown>(url, 'createModel', { ...m }),
```

`frontend/src/store/settings.ts`: change `ExportNote` to
```ts
export interface ExportNote { deckName: string; modelName: string; fields: { sentence: string; pinyin?: string; translation?: string; audio: string; source?: string; link?: string } }
```

`frontend/src/anki/listening.ts`:
```ts
import type { ExportNote } from '../store/settings'
import { anki, type NewModel } from './client'

// Listening cards (addendum §5.1): the sentence's audio on the front, what was said on the back.
export const LISTENING_DECK = 'shadow-speech'
export const LISTENING_MODEL = 'Shadow Listening'
export const LISTENING_FIELDS = ['Audio', 'Sentence', 'Pinyin', 'Translation', 'Source', 'Link']

export const listeningModel: NewModel = {
  modelName: LISTENING_MODEL,
  inOrderFields: LISTENING_FIELDS,
  isCloze: false,
  css: [
    '.card { font-family: "Noto Sans SC", "Inter", sans-serif; font-size: 20px; text-align: center; color: #1b1f24; background: #fafafa; }',
    '.prompt { color: #7c8793; margin-top: 1em; }',
    '.sentence { font-size: 34px; margin: .4em 0; }',
    '.pinyin { color: #4a86c8; }',
    '.translation { color: #555; font-style: italic; margin-top: .3em; }',
    '.source { font-size: 14px; color: #7c8793; margin-top: 1.2em; }',
    '.nightMode .card, .night_mode .card { color: #cfd6dd; background: #111418; }',
  ].join('\n'),
  cardTemplates: [{
    Name: 'Listening',
    Front: '{{Audio}}\n<div class="prompt">What did you hear?</div>',
    Back: [
      '{{FrontSide}}',
      '<hr id="answer">',
      '<div class="sentence">{{Sentence}}</div>',
      '<div class="pinyin">{{Pinyin}}</div>',
      '<div class="translation">{{Translation}}</div>',
      '<div class="source">{{#Link}}<a href="{{Link}}">{{Source}}</a>{{/Link}}{{^Link}}{{Source}}{{/Link}}</div>',
    ].join('\n'),
  }],
}

export interface ListeningSetup { deckCreated: boolean; modelCreated: boolean; exportNote: ExportNote }

// Creates the deck and the note type unless they exist (an existing one is used as it is, never changed) and returns
// the export settings that use them. AnkiConnect errors propagate with AnkiConnect's own message.
export async function setupListeningDeck(ankiUrl: string): Promise<ListeningSetup> {
  const a = anki(ankiUrl)
  const deckCreated = !(await a.deckNames()).includes(LISTENING_DECK)
  if (deckCreated) await a.createDeck(LISTENING_DECK)
  const modelCreated = !(await a.modelNames()).includes(LISTENING_MODEL)
  if (modelCreated) await a.createModel(listeningModel)
  const have = modelCreated ? LISTENING_FIELDS : await a.modelFieldNames(LISTENING_MODEL)
  if (!have.includes('Sentence') || !have.includes('Audio')) {
    throw new Error(`The existing note type "${LISTENING_MODEL}" has no Sentence or Audio field. Rename it in Anki, then set up again.`)
  }
  const fields: ExportNote['fields'] = { sentence: 'Sentence', audio: 'Audio' }
  for (const [key, name] of [['pinyin', 'Pinyin'], ['translation', 'Translation'], ['source', 'Source'], ['link', 'Link']] as const) {
    if (have.includes(name)) fields[key] = name
  }
  return { deckCreated, modelCreated, exportNote: { deckName: LISTENING_DECK, modelName: LISTENING_MODEL, fields } }
}
```

- [ ] **Step 4: Export fields and tags**

In `frontend/src/anki/export.ts` add after the imports:
```ts
// The lesson a sentence comes from, for the Source and Link fields.
export interface LessonRef { id: number; title: string; source_type: string; source_ref: string }

export const mmss = (s: number): string => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`
// "<lesson title> · mm:ss" (addendum §5.1).
export const sourceText = (lesson: LessonRef, seg: Segment): string => `${lesson.title} · ${mmss(seg.start_s)}`
// The video at the sentence's second, for YouTube lessons; '' otherwise.
export function youtubeLink(lesson: LessonRef, seg: Segment): string {
  if (lesson.source_type !== 'youtube' || !lesson.source_ref.startsWith('youtube::')) return ''
  return `https://www.youtube.com/watch?v=${lesson.source_ref.slice('youtube::'.length)}&t=${Math.floor(seg.start_s)}`
}
```
replace `buildExportNote` with:
```ts
// One sentence as a new Anki note in the configured note type: text, pinyin (per word), translation, source and link
// (when mapped and the lesson is known) and the clip.
export function buildExportNote(seg: Segment, mp3b64: string, cfg: ExportNote, allowDuplicate = false, lesson?: LessonRef): AddNote {
  const fields: Record<string, string> = { [cfg.fields.sentence]: seg.text }
  if (cfg.fields.pinyin) fields[cfg.fields.pinyin] = (seg.words_json ?? []).map((w) => w.pinyin).join(' ')
  if (cfg.fields.translation && seg.translation) fields[cfg.fields.translation] = seg.translation
  if (lesson && cfg.fields.source) fields[cfg.fields.source] = sourceText(lesson, seg)
  const link = lesson ? youtubeLink(lesson, seg) : ''
  if (link && cfg.fields.link) fields[cfg.fields.link] = link
  return {
    deckName: cfg.deckName, modelName: cfg.modelName, fields, tags: ['shadow', `shadow::${seg.lesson_id}`],
    options: { allowDuplicate, duplicateScope: 'deck' },
    audio: [{ filename: `shadow_${seg.id}.mp3`, data: mp3b64, fields: [cfg.fields.audio] }],
  }
}
```
and replace `exportToAnki` and `exportAndRecord` with:
```ts
// Sends one sentence to Anki (the only write to Anki the app makes). A duplicate in the deck is added only when
// the user confirms it. Resolves to the new note id.
export async function exportToAnki(seg: Segment, ankiUrl: string, cfg: ExportNote, lesson?: LessonRef): Promise<number> {
  // no-cache: revalidate, so a clip re-cut by an edit in another tab or before a reload is never sent stale
  const res = await fetch(api.segments.audioUrl(seg.id, 'mp3'), { cache: 'no-cache' })
  if (!res.ok) throw new Error(`Could not get the sentence clip: ${res.status} ${res.statusText}`)
  const b64 = await blobToBase64(await res.blob())
  try { return await addNote(ankiUrl, buildExportNote(seg, b64, cfg, false, lesson)) }
  catch (e) {
    if (!/duplicate/i.test((e as Error).message)) throw e
    if (!window.confirm(`"${seg.text}" is already in the Anki deck ${cfg.deckName}. Add it anyway?`)) throw new Error(`"${seg.text}" is already in Anki, not added again.`)
    return addNote(ankiUrl, buildExportNote(seg, b64, cfg, true, lesson))
  }
}
```
```ts
// Sends one sentence and records the new note on it (so Review skips it and A asks first); resolves to the
// updated sentence. A sentence imported from Anki keeps its own note id, which a re-import identifies it by.
export async function exportAndRecord(seg: Segment, ankiUrl: string, cfg: ExportNote, lesson?: LessonRef): Promise<Segment> {
  const noteId = await exportToAnki(seg, ankiUrl, cfg, lesson)
  if (inAnki(seg)) return seg
  try { return await api.segments.patch(seg.id, { anki_note_id: noteId }) }
  catch (e) {
    const why = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
    throw new Error(`"${seg.text}" was sent to Anki, but could not be marked as sent: ${why}`)
  }
}
```

`frontend/src/pages/Practice.tsx` (`sendToAnki`): replace `const updated = await exportAndRecord(s, ankiUrl, exportNote); sent++` with
```tsx
          const updated = await exportAndRecord(s, ankiUrl, exportNote, usePractice.getState().lesson ?? undefined); sent++
```
`frontend/src/pages/Review.tsx` (`sendAll`): replace `mark(await exportAndRecord(r.segment, ankiUrl, exportNote))` with `mark(await exportAndRecord(r.segment, ankiUrl, exportNote, r.lesson))`.

- [ ] **Step 5: Settings**

In `frontend/src/pages/Settings.tsx`:
- add `import { LISTENING_DECK, LISTENING_MODEL, setupListeningDeck } from '../anki/listening'`;
- after `connect` add:
```tsx
  // Addendum §5.1: create (or reuse, unchanged) the deck and note type for listening cards and export there.
  async function setupDeck() {
    if (!window.confirm(`Create the Anki deck "${LISTENING_DECK}" and the note type "${LISTENING_MODEL}" (unless they exist) and send exports there?`)) return
    try {
      const r = await setupListeningDeck(s.ankiUrl)
      s.set({ exportNote: r.exportNote })
      setStatus(`${r.deckCreated ? 'Created' : 'Using the existing'} deck ${LISTENING_DECK}, ${r.modelCreated ? 'created' : 'using the existing'} note type ${LISTENING_MODEL}. Exports now make listening cards there.`)
      const a = anki(s.ankiUrl)
      a.deckNames().then(setDecks).catch(() => {})
      a.modelNames().then(setModels).catch(() => {})
    } catch (e) {
      setStatus(`Could not set up the deck. AnkiConnect said: ${e instanceof Error ? e.message : String(e)}`)
    }
  }
```
- right after `<p className="text-sm text-fgdim">{status}</p>` add:
```tsx
        <div className="flex gap-2 items-center">
          <button className="btn" onClick={() => void setupDeck()}>Set up shadow-speech deck</button>
          <span className="text-xs text-fgdim">Listening cards: the sentence's audio on the front, sentence, pinyin, translation and a link to the video on the back.</span>
        </div>
```
- in the export mapping replace `(['sentence', 'pinyin', 'translation', 'audio'] as const)` with `(['sentence', 'pinyin', 'translation', 'audio', 'source', 'link'] as const)`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run && npx eslint src`
Expected: PASS; no eslint errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/anki/listening.ts frontend/src/anki/listening.test.ts frontend/src/anki/client.ts frontend/src/anki/client.test.ts frontend/src/anki/export.ts frontend/src/anki/export.test.ts frontend/src/store/settings.ts frontend/src/pages/Settings.tsx frontend/src/pages/Settings.test.tsx frontend/src/pages/Practice.tsx frontend/src/pages/Practice.test.tsx frontend/src/pages/Review.tsx
git commit -m "feat(frontend): Shadow Listening note type set-up; Source, Link and lesson tag on exports"
```

---

### Task 17: Frontend — session-end export dialog

**Files:**
- Create: `frontend/src/lib/sessionExport.ts`, `frontend/src/lib/sessionExport.test.ts`, `frontend/src/components/ExportList.tsx`, `frontend/src/components/ExportList.test.tsx`, `frontend/src/components/SessionExportDialog.tsx`
- Modify: `frontend/src/components/Transport.tsx` (Finish session), `frontend/src/components/TopBar.tsx` (`onBack`), `frontend/src/pages/Practice.tsx`, `frontend/src/pages/Practice.test.tsx`

**Interfaces:**
- Consumes: Task 16 (`exportAndRecord(seg, ankiUrl, cfg, lesson)`, `LessonRef`), Task 10 (`practised`), Task 11 (`speechChars`).
- Produces (Task 18 reuses `ExportList`):
  - `isFiller(text: string): boolean`, `sessionUnsent(segments: Segment[], practised: readonly number[]): Segment[]`, `initialSelection(segments: Segment[]): Set<number>`
  - `export interface ExportItem { segment: Segment; lesson: LessonRef }`; `ExportList({ items: ExportItem[]; onSent: (seg: Segment) => void })` — checkboxes named by the sentence, fillers unticked, button `Send N to Anki`, per-row `sent ✓` / `sending…` / the error
  - `SessionExportDialog({ items, onSent, onClose })` — `role="dialog"` named "Send what you practised to Anki?", button "Close", Esc closes
  - `Transport` prop `onFinish: () => void` (button "Finish session"); `TopBar` prop `onBack?: (e: MouseEvent<HTMLAnchorElement>) => void`

- [ ] **Step 1: Write the failing tests**

`frontend/src/lib/sessionExport.test.ts`:
```ts
import { describe, expect, it } from 'vitest'
import type { Segment } from '../api/types'
import { initialSelection, isFiller, sessionUnsent } from './sessionExport'

const seg = (id: number, text: string, anki_note_id: number | null = null): Segment => ({
  id, lesson_id: 1, idx: id, start_s: 0, end_s: 1, text, translation: null, words_json: null, ref_alignment_json: null,
  difficulty_flag: false, anki_note_id, last_score: null, best_score: null, attempts: 1,
})

describe('session export', () => {
  it.each([
    ['好的。', true], ['嗯嗯，对对。', true], ['是的是的，好的。', true], ['啊？', true], ['嗯嗯嗯嗯嗯', true], ['ABC', true],
    ['我今天想学中文。', false], ['对，我觉得是', false], ['我们走吧', false],
  ])('isFiller(%s) = %s', (text, want) => { expect(isFiller(text)).toBe(want) })

  it("lists this session's practised sentences not in Anki, in lesson order", () => {
    const segs = [seg(1, '我们走吧'), seg(2, '好的'), seg(3, '我今天想学中文', 9), seg(4, '再见再见吧')]
    expect(sessionUnsent(segs, [4, 1, 3]).map((s) => s.id)).toEqual([1, 4])
    expect([...initialSelection(segs)]).toEqual([1, 3, 4])
  })
})
```

`frontend/src/components/ExportList.test.tsx`:
```tsx
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Segment } from '../api/types'
import { useSettings } from '../store/settings'

const h = vi.hoisted(() => ({ exportAndRecord: vi.fn() }))
vi.mock('../anki/export', async (importOriginal) => ({ ...(await importOriginal<typeof import('../anki/export')>()), exportAndRecord: h.exportAndRecord }))
import ExportList from './ExportList'

const seg = (id: number, text: string): Segment => ({
  id, lesson_id: 1, idx: id, start_s: 0, end_s: 1, text, translation: null, words_json: null, ref_alignment_json: null,
  difficulty_flag: false, anki_note_id: null, last_score: null, best_score: null, attempts: 1,
})
const lesson = { id: 1, title: 'L', source_type: 'youtube', source_ref: 'youtube::abcDEF12345' }
const items = [{ segment: seg(1, '我今天想学中文。'), lesson }, { segment: seg(2, '嗯嗯，对对。'), lesson }, { segment: seg(3, '好的。'), lesson }]
const cfg = { deckName: 'shadow-speech', modelName: 'Shadow Listening', fields: { sentence: 'Sentence', audio: 'Audio' } }
const show = (onSent = vi.fn()) => render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><ExportList items={items} onSent={onSent} /></MemoryRouter>)

describe('<ExportList>', () => {
  beforeEach(() => { h.exportAndRecord.mockReset(); useSettings.setState({ exportNote: cfg }) })
  afterEach(() => { cleanup(); useSettings.setState({ exportNote: null }) })

  it('ticks every sentence except fillers', () => {
    show()
    expect(screen.getByRole('checkbox', { name: /我今天想学中文/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /嗯嗯，对对/ })).not.toBeChecked()
    expect(screen.getByRole('checkbox', { name: /好的/ })).not.toBeChecked()
    expect(screen.getByRole('button', { name: 'Send 1 to Anki' })).toBeEnabled()
  })

  it('sends the ticked rows with their lesson and shows a result per row', async () => {
    const onSent = vi.fn()
    h.exportAndRecord.mockImplementation(async (s: Segment) => ({ ...s, anki_note_id: 9 }))
    show(onSent)
    fireEvent.click(screen.getByRole('checkbox', { name: /好的/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Send 2 to Anki' }))
    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(2))
    expect(h.exportAndRecord.mock.calls.map((c) => [(c[0] as Segment).id, c[3]])).toEqual([[1, lesson], [3, lesson]])
    expect(screen.getAllByText('sent ✓')).toHaveLength(2)
    expect(screen.getByRole('button', { name: 'Send 0 to Anki' })).toBeDisabled()
  })

  it('with Anki unreachable each row shows its error, nothing is marked sent, and the row stays ticked', async () => {
    const onSent = vi.fn()
    h.exportAndRecord.mockRejectedValue(new Error('Cannot reach AnkiConnect at http://127.0.0.1:8765.'))
    show(onSent)
    fireEvent.click(screen.getByRole('button', { name: 'Send 1 to Anki' }))
    expect(await screen.findByText(/Cannot reach AnkiConnect/)).toBeInTheDocument()
    expect(onSent).not.toHaveBeenCalled()
    expect(screen.getByRole('checkbox', { name: /我今天想学中文/ })).toBeChecked()
    expect(screen.getByRole('button', { name: 'Send 1 to Anki' })).toBeEnabled()
  })

  it('without an export note type it points to Settings', () => {
    useSettings.setState({ exportNote: null })
    show()
    expect(screen.getByText(/Set up the Anki export in Settings first/)).toBeInTheDocument()
  })
})
```

In `frontend/src/pages/Practice.test.tsx`, append inside `describe('<Practice>', …)`:
```tsx
  describe('session-end export', () => {
    const cfg = { deckName: 'shadow-speech', modelName: 'Shadow Listening', fields: { sentence: 'Sentence', audio: 'Audio' } }
    const long: LessonDetail = { ...lesson, segments: [seg(11, 0, '我今天想学中文'), seg(12, 1, '再见')] }
    beforeEach(() => { useSettings.setState({ exportNote: cfg }); h.api.lessons.get.mockResolvedValue(long) })
    afterEach(() => { cleanup(); useSettings.setState({ exportNote: null }) })
    const renderWithLibrary = () => render(
      <MemoryRouter initialEntries={['/practice/1']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes><Route path="/practice/:id" element={<Practice />} /><Route path="/library" element={<div>library page</div>} /></Routes>
      </MemoryRouter>)
    async function takeOne() {
      await screen.findByText('我今天想学中文', { selector: 'p.sentence' })
      press('Enter'); await flush(); press('Enter'); await flush()
      await waitFor(() => expect(usePractice.getState().practised).toEqual([11]))
    }

    it('Finish session offers the practised sentences, sends them, then goes to the library', async () => {
      h.exportAndRecord.mockImplementation(async (s: Segment) => ({ ...s, anki_note_id: 5 }))
      renderWithLibrary()
      await takeOne()
      fireEvent.click(screen.getByRole('button', { name: 'Finish session' }))
      const dialog = await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      fireEvent.click(within(dialog).getByRole('button', { name: 'Send 1 to Anki' }))
      expect(await within(dialog).findByText('sent ✓')).toBeInTheDocument()
      expect(h.exportAndRecord).toHaveBeenCalledWith(expect.objectContaining({ id: 11 }), useSettings.getState().ankiUrl, cfg, expect.objectContaining({ id: 1 }))
      expect(usePractice.getState().lesson!.segments[0].anki_note_id).toBe(5)
      fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
      expect(await screen.findByText('library page')).toBeInTheDocument()
    })

    it('fillers start unticked', async () => {
      h.api.lessons.get.mockResolvedValue(lesson)                 // 你好: two characters
      renderWithLibrary()
      await screen.findByText('你好', { selector: 'p.sentence' })
      press('Enter'); await flush(); press('Enter'); await flush()
      await waitFor(() => expect(usePractice.getState().practised).toEqual([11]))
      fireEvent.click(screen.getByRole('button', { name: 'Finish session' }))
      const dialog = await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      expect(within(dialog).getByRole('checkbox', { name: /你好/ })).not.toBeChecked()
    })

    it('the back link asks first when something practised is not in Anki', async () => {
      renderWithLibrary()
      await takeOne()
      fireEvent.click(screen.getByTitle('Back to the library'))
      expect(await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })).toBeInTheDocument()
      expect(screen.queryByText('library page')).toBeNull()
      fireEvent.click(screen.getByRole('button', { name: 'Close' }))
      expect(await screen.findByText('library page')).toBeInTheDocument()
    })

    it('with nothing to send, the back link and Finish session leave at once', async () => {
      renderWithLibrary()
      await screen.findByText('我今天想学中文', { selector: 'p.sentence' })
      fireEvent.click(screen.getByTitle('Back to the library'))
      expect(await screen.findByText('library page')).toBeInTheDocument()
      expect(screen.queryByRole('dialog')).toBeNull()
    })
  })
```
and inside `describe('Flow', …)`:
```tsx
    it("closing the summary offers the run's sentences before the setup comes back", async () => {
      useSettings.setState({ exportNote: { deckName: 'D', modelName: 'M', fields: { sentence: 'S', audio: 'A' } } })
      clipsTake(2)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('along')
      await screen.findByText(/Flow finished · 2 sentences/)
      await waitFor(() => expect(usePractice.getState().practised).toEqual([11, 12]))
      fireEvent.click(screen.getByRole('button', { name: 'done' }))
      const dialog = await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      expect(within(dialog).getAllByRole('checkbox')).toHaveLength(2)
      fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
      expect(await screen.findByRole('button', { name: 'Start' })).toBeInTheDocument()
      useSettings.setState({ exportNote: null })
    })
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/lib/sessionExport.test.ts src/components/ExportList.test.tsx src/pages/Practice.test.tsx`
Expected: FAIL — the new modules cannot be resolved; no "Finish session" button; no dialog.

- [ ] **Step 3: Selection logic**

`frontend/src/lib/sessionExport.ts`:
```ts
import type { Segment } from '../api/types'
import { speechChars } from './text'

const INTERJECTIONS = /^(?:嗯|啊|哦|呃|对|好的|是的|好|是)+$/

// Not worth a listening card (addendum §5.2): fewer than 4 speech characters, or nothing but interjections
// (嗯 啊 哦 呃 对 好 是, and so 嗯嗯 对对 好的 是的).
export function isFiller(text: string): boolean {
  const s = speechChars(text)
  return s.length < 4 || INTERJECTIONS.test(s.join(''))
}

// This session's practised sentences that have no Anki note, in lesson order.
export function sessionUnsent(segments: Segment[], practised: readonly number[]): Segment[] {
  const ids = new Set(practised)
  return segments.filter((s) => ids.has(s.id) && s.anki_note_id == null)
}

// Ticked at first: everything but fillers.
export function initialSelection(segments: Segment[]): Set<number> {
  return new Set(segments.filter((s) => !isFiller(s.text)).map((s) => s.id))
}
```

- [ ] **Step 4: The list and the dialog**

`frontend/src/components/ExportList.tsx`:
```tsx
import { useState } from 'react'
import { Link } from 'react-router-dom'
import { exportAndRecord, type LessonRef } from '../anki/export'
import type { Segment } from '../api/types'
import { initialSelection, isFiller } from '../lib/sessionExport'
import { useSettings } from '../store/settings'

export interface ExportItem { segment: Segment; lesson: LessonRef }
type RowState = { status: 'sending' } | { status: 'sent' } | { status: 'failed'; error: string }

// Practised sentences to send to Anki as listening cards (addendum §5.2): all ticked except fillers; one click sends
// the ticked ones one after another; each row shows its own result. A failed row stays ticked for another try.
export default function ExportList({ items, onSent }: { items: ExportItem[]; onSent: (seg: Segment) => void }) {
  const { ankiUrl, exportNote } = useSettings()
  const [picked, setPicked] = useState(() => initialSelection(items.map((i) => i.segment)))
  const [rows, setRows] = useState<Record<number, RowState>>({})
  const [busy, setBusy] = useState(false)
  const todo = items.filter((it) => picked.has(it.segment.id) && rows[it.segment.id]?.status !== 'sent')
  if (!exportNote) {
    return <p className="text-sm text-fgdim">Set up the Anki export in Settings first (<Link className="underline" to="/settings">Settings → Anki → Set up shadow-speech deck</Link>).</p>
  }
  const cfg = exportNote
  const toggle = (id: number) => setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n })
  async function send() {
    if (busy) return
    setBusy(true)
    for (const it of todo) {
      const id = it.segment.id
      setRows((r) => ({ ...r, [id]: { status: 'sending' } }))
      try {
        const seg = await exportAndRecord(it.segment, ankiUrl, cfg, it.lesson)
        setRows((r) => ({ ...r, [id]: { status: 'sent' } }))
        onSent(seg)
      } catch (e) {
        setRows((r) => ({ ...r, [id]: { status: 'failed', error: e instanceof Error ? e.message : String(e) } }))
      }
    }
    setBusy(false)
  }
  return (
    <div className="space-y-2">
      <ul className="space-y-1">{items.map(({ segment: s }) => {
        const row = rows[s.id]
        return (
          <li key={s.id} className="text-sm">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={picked.has(s.id)} disabled={busy || row?.status === 'sent'} onChange={() => toggle(s.id)} />
              <span className="font-hanzi flex-1">{s.text}</span>
              {isFiller(s.text) && <span className="text-[10px] text-fgdim">filler</span>}
              {row && <span className={`text-xs ${row.status === 'failed' ? 'text-bad' : 'text-fgdim'}`}>
                {row.status === 'sent' ? 'sent ✓' : row.status === 'sending' ? 'sending…' : row.error}</span>}
            </label>
          </li>)
      })}</ul>
      <button className="btn" onClick={() => void send()} disabled={busy || !todo.length}>Send {todo.length} to Anki</button>
    </div>
  )
}
```

`frontend/src/components/SessionExportDialog.tsx`:
```tsx
import { useEffect } from 'react'
import type { Segment } from '../api/types'
import ExportList, { type ExportItem } from './ExportList'

// End of a session (Finish session, closing the Flow summary, the back link): this session's practised sentences that
// are not in Anki yet. Closing without sending loses nothing: they stay in Review → Practised, not in Anki.
export default function SessionExportDialog({ items, onSent, onClose }: { items: ExportItem[]; onSent: (seg: Segment) => void; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center">
      <div role="dialog" aria-modal="true" aria-labelledby="session-export-title" className="bg-panel border border-line rounded p-4 w-[560px] max-h-[80vh] overflow-y-auto space-y-3">
        <h3 id="session-export-title" className="text-fghi">Send what you practised to Anki?</h3>
        <p className="text-sm text-fgdim">Each sentence becomes a listening card. Fillers start unticked. Whatever you don't send stays in Review → Practised, not in Anki.</p>
        <ExportList items={items} onSent={onSent} />
        <div className="flex justify-end"><button className="btn" onClick={onClose}>Close</button></div>
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Transport, top bar and Practice**

`frontend/src/components/Transport.tsx`: add `onFinish: () => void` to `Props` and to the destructured parameters, and after the Next button (`<button className={b} onClick={() => onAction('next')} title="Next (→)">▶</button>`) add
```tsx
        <button className={b} onClick={onFinish} title="End the session; offers to send what you practised to Anki">Finish session</button>
```

`frontend/src/components/TopBar.tsx`: add `import type { MouseEvent } from 'react'`, add `onBack?: (e: MouseEvent<HTMLAnchorElement>) => void` to `Props` and to the destructured parameters, and change the back link to
```tsx
      <span><Link to="/library" onClick={onBack} className="mr-3 hover:text-fghi" title="Back to the library">←</Link>
```

`frontend/src/pages/Practice.tsx`:
- change the router import to `import { Link, useNavigate, useParams } from 'react-router-dom'`; add
```tsx
import type { ExportItem } from '../components/ExportList'
import SessionExportDialog from '../components/SessionExportDialog'
import { sessionUnsent } from '../lib/sessionExport'
```
- after `const mic = useMic()` add `const navigate = useNavigate()`;
- replace
```tsx
  const dialogOpen = useRef(false)
  dialogOpen.current = dialog != null
```
with
```tsx
  // The session-end export dialog (addendum §5.2) and what to do once it closes.
  const [exportPrompt, setExportPrompt] = useState<{ items: ExportItem[]; after: () => void } | null>(null)
  const dialogOpen = useRef(false)
  dialogOpen.current = dialog != null || exportPrompt != null
```
- after `exportWeakest` add:
```tsx
  // This session's practised sentences with no Anki note.
  function unsentItems(): ExportItem[] {
    const ps = usePractice.getState(), l = ps.lesson
    return l ? sessionUnsent(l.segments, ps.practised).map((segment) => ({ segment, lesson: l })) : []
  }
  // Offers them before `after` (leaving the page, closing the Flow summary); with none, runs `after` at once.
  function offerExport(after: () => void) {
    const items = unsentItems()
    if (!items.length) { after(); return }
    cancelActivity()
    setExportPrompt({ items, after })
  }
  function closeExport() {
    const p = exportPrompt
    setExportPrompt(null)
    p?.after()
  }
```
- add to `<TopBar … />`:
```tsx
        onBack={(e) => { if (unsentItems().length) { e.preventDefault(); offerExport(() => navigate('/library')) } }}
```
- in `<FlowSummary … />` replace `onDone={flow.clear}` with `onDone={() => offerExport(flow.clear)}`;
- add to `<Transport … />`: `onFinish={() => offerExport(() => navigate('/library'))}`;
- next to the `{help && <HelpOverlay … />}` line add:
```tsx
      {exportPrompt && <SessionExportDialog items={exportPrompt.items} onSent={(s) => usePractice.getState().updateSegment(s)} onClose={closeExport} />}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run && npx eslint src`
Expected: PASS; no eslint errors. (The existing test "scores still refresh when the summary is closed while uploads are in flight" still closes the summary at once: nothing is practised until an upload succeeds.)

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/sessionExport.ts frontend/src/lib/sessionExport.test.ts frontend/src/components/ExportList.tsx frontend/src/components/ExportList.test.tsx frontend/src/components/SessionExportDialog.tsx frontend/src/components/Transport.tsx frontend/src/components/TopBar.tsx frontend/src/pages/Practice.tsx frontend/src/pages/Practice.test.tsx
git commit -m "feat(frontend): session-end dialog sends practised sentences to Anki as listening cards"
```

---

### Task 18: Frontend — "Practised, not in Anki" on the Review page; acceptance checklist

**Files:**
- Modify: `frontend/src/api/types.ts`, `frontend/src/api/client.ts`, `frontend/src/pages/Review.tsx`, `frontend/src/pages/Review.test.tsx`
- Modify: `docs/phase1-acceptance.md` (new section)

**Interfaces:**
- Consumes: `GET /review/unexported` (Task 15), `ExportList`, `ExportItem` (Task 17), `LessonRef` (Task 16).
- Produces: `interface UnexportedItem { lesson_id: number; lesson_title: string; lesson_source_type: Lesson['source_type']; lesson_source_ref: string; last_attempt_at: string; segment: Segment }`; `api.review.unexported(): Promise<UnexportedItem[]>`.

- [ ] **Step 1: Write the failing test**

In `frontend/src/pages/Review.test.tsx`:
- change the hoisted mock to
```tsx
const h = vi.hoisted(() => ({
  api: { lessons: { list: vi.fn(), get: vi.fn() }, review: { unexported: vi.fn() } },
  exportAndRecord: vi.fn(),
}))
```
- add `beforeEach` to the vitest import and, at the top of the `describe` block, `beforeEach(() => { h.exportAndRecord.mockReset(); h.api.review.unexported.mockResolvedValue([]) })`;
- append inside the `describe`:
```tsx
  it('lists practised sentences not in Anki and sends them with the same bulk send', async () => {
    useSettings.setState({ exportNote: { deckName: 'shadow-speech', modelName: 'Shadow Listening', fields: { sentence: 'Sentence', audio: 'Audio' } } })
    h.api.lessons.list.mockResolvedValue([])
    h.api.review.unexported.mockResolvedValue([{ lesson_id: 3, lesson_title: 'YT', lesson_source_type: 'youtube', lesson_source_ref: 'youtube::abcDEF12345',
      last_attempt_at: '2026-10-07T09:05:00', segment: { ...seg(5, '我今天想学中文', null), difficulty_flag: false } }])
    h.exportAndRecord.mockImplementation(async (s: Segment) => ({ ...s, anki_note_id: 9 }))
    render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Review /></MemoryRouter>)
    expect(await screen.findByText('Practised, not in Anki · 1')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Send 1 to Anki' }))
    expect(await screen.findByText('sent ✓')).toBeInTheDocument()
    expect(h.exportAndRecord.mock.calls[0][3]).toEqual({ id: 3, title: 'YT', source_type: 'youtube', source_ref: 'youtube::abcDEF12345' })
  })
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/Review.test.tsx`
Expected: FAIL — no "Practised, not in Anki" heading.

- [ ] **Step 3: Implement**

`frontend/src/api/types.ts`: add
```ts
export interface UnexportedItem {
  lesson_id: number; lesson_title: string; lesson_source_type: Lesson['source_type']; lesson_source_ref: string
  last_attempt_at: string; segment: Segment
}
```
`frontend/src/api/client.ts`: add `UnexportedItem` to the type import and, after `stats`, add
```ts
  review: {
    unexported: () => req<UnexportedItem[]>('/review/unexported'),
  },
```

Replace `frontend/src/pages/Review.tsx` with:
```tsx
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { LessonDetail, Segment, UnexportedItem } from '../api/types'
import ExportList, { type ExportItem } from '../components/ExportList'
import Shell from '../components/Shell'
import { flaggedFirst } from '../lib/stats'
import { exportAndRecord, splitForExport } from '../anki/export'
import { useSettings } from '../store/settings'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
const toItem = (u: UnexportedItem): ExportItem => ({
  segment: u.segment, lesson: { id: u.lesson_id, title: u.lesson_title, source_type: u.lesson_source_type, source_ref: u.lesson_source_ref },
})

// Sentences worth another go (flagged, or from Phase 2 last scored below 0.6), and every practised sentence that is not
// in Anki yet (addendum §5.2: nothing is lost when Anki was closed at the end of a session).
export default function Review() {
  const [lessons, setLessons] = useState<LessonDetail[]>([])
  const [unsent, setUnsent] = useState<UnexportedItem[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState('')
  const [sending, setSending] = useState(false)
  const { ankiUrl, exportNote } = useSettings()
  useEffect(() => {
    let cancelled = false
    api.lessons.list()
      .then((ls) => Promise.all(ls.filter((l) => l.status === 'ready').map((l) => api.lessons.get(l.id))))
      .then((d) => { if (!cancelled) setLessons(d) })
      .catch((e) => { if (!cancelled) setMsg(`Could not load lessons: ${message(e)}`) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])
  useEffect(() => {
    let cancelled = false
    api.review.unexported()
      .then((u) => { if (!cancelled) setUnsent(u) })
      .catch((e) => { if (!cancelled) setMsg(`Could not load the practised sentences: ${message(e)}`) })
    return () => { cancelled = true }
  }, [])
  const rows = flaggedFirst(lessons)
  // each sent sentence is marked in Anki, so sending again skips it
  const mark = (seg: Segment) => setLessons((ls) => ls.map((l) => (l.id !== seg.lesson_id ? l : { ...l, segments: l.segments.map((x) => (x.id === seg.id ? seg : x)) })))
  async function sendAll() {
    if (!exportNote) { setMsg('Configure the export note type in Settings'); return }
    setSending(true); setMsg('')
    const { todo, skipped } = splitForExport(rows)
    let n = 0; const failures: string[] = []
    for (const r of todo) { try { mark(await exportAndRecord(r.segment, ankiUrl, exportNote, r.lesson)); n++ } catch (e) { failures.push(message(e)) } }
    setMsg(`${n} sent to Anki${skipped ? ` · ${skipped} skipped (already in Anki)` : ''}${failures.length ? ` · ${failures.length} failed: ${[...new Set(failures)].join('; ')}` : ''}`)
    setSending(false)
  }
  return (
    <Shell><div className="max-w-4xl mx-auto p-6 space-y-3">
      <div className="flex justify-between items-center"><h1 className="text-fghi">Review · {rows.length}</h1><button className="btn" onClick={sendAll} disabled={!rows.length || sending}>A → Anki all</button></div>
      {msg && <p className="text-sm text-fgdim">{msg}</p>}
      {!loading && !rows.length && !msg && <p className="text-sm text-fgdim">Nothing to review. Flag a sentence with ⚑ while practising and it shows up here.</p>}
      {rows.map((r) => (
        <div key={r.segment.id} className="flex items-center gap-3 border-b border-line py-2 text-sm">
          <span className="text-fgdim w-32 truncate">{r.lesson.title}</span><span className="font-hanzi flex-1">{r.segment.text}</span>
          <span className="text-fgdim">{r.segment.difficulty_flag ? '⚑' : ''} {r.segment.last_score != null ? Math.round(r.segment.last_score * 100) : ''}</span>
          <Link className="btn" to={`/practice/${r.lesson.id}?seg=${r.segment.idx}`}>Practise</Link>
        </div>))}
      <section className="space-y-2 pt-6">
        <h2 className="text-fghi">Practised, not in Anki{unsent ? ` · ${unsent.length}` : ''}</h2>
        {unsent && (unsent.length
          ? <ExportList items={unsent.map(toItem)} onSent={mark} />
          : <p className="text-sm text-fgdim">Every sentence you practised is in Anki.</p>)}
      </section>
    </div></Shell>
  )
}
```

Append to `docs/phase1-acceptance.md`:
```markdown

## Phase 1.5: YouTube, passages, guidance, listening cards (manual)

- [ ] Aligner: the MMS_FA comparison ran on lesson 1 and its verdict is in the plan ledger (`docs/superpowers/plans/2026-10-07-youtube-passages-guidance.md`); after re-ingesting lesson 1, clips no longer start a second early and syllable clicks play the right syllable.
- [ ] A real YouTube video with Chinese subtitles: paste the link in the Library; the tile shows the `download` stage, then the lesson has the video's title and channel (simplified) and the subtitle text.
- [ ] A real YouTube video without Chinese subtitles: the lesson uses the ASR text.
- [ ] A video that needs sign-in (age-restricted): without `[youtube] cookies_file` the tile shows "this video needs a cookies file — see Settings" and can be deleted; with a cookies file it ingests.
- [ ] Brave bookmarklet: drag "→ shadow-speech" from Settings to the bookmarks bar, click it on a YouTube video: the app asks "Add … to shadow-speech?", adds it, and the address bar shows `/library` without `?add=`. Adding the same video again creates no second lesson.
- [ ] A video with chapters: passages are named after the chapters; a long video without chapters has "Passage N · mm:ss–mm:ss" passages of about 2–3 minutes.
- [ ] Practice: "Passage 4 / 9" in the top bar jumps between passages; Flow's range defaults to the current passage; the drawer groups sentences under passage headers with ✓ once every sentence has an attempt; the library tile shows "n / m passages".
- [ ] Help: the overlay opens on the first visit only; `?` opens and closes it, Esc closes it; hovering a mode tab shows its description.
- [ ] Cue line: says Listen / Your turn — speak now / Speak along / Ready / Done at the right moments in every mode; the mic meter moves when you speak.
- [ ] Yomitan over a wiping sentence: during reference playback, hover 今天: the popup shows the two-character word, with pinyin on and off.
- [ ] Karaoke: the sentence colours in sync with the audio; in Echo the count-in dots then the amber ghost wipe run while you record; in Flow after the turn bar shrinks over the pause; in Flow along the next line is shown dimmed below the current one.
- [ ] Volume: the reference volume slider changes playback and survives a reload; in Flow along and Chorus the guide level is audibly quieter than the reference volume and adjustable live; your own takes play at the reference volume; the headphones hint appears once.
- [ ] Anki: Settings → "Set up shadow-speech deck" creates the deck and the "Shadow Listening" note type (or reuses them); a listening card's front plays the audio and asks "What did you hear?"; its back shows the sentence, pinyin, translation and the Source link opening the video at the right second.
- [ ] Session end: "Finish session", closing the Flow summary and the ← link offer this session's practised sentences with fillers unticked; with Anki closed each row shows an error and the sentences are listed in Review → "Practised, not in Anki", from where they can be sent later.
```

- [ ] **Step 4: Run the whole suite**

Run: `cd ~/shadow-speech && make test`
Expected: backend `passed` (models deselected), vitest all files pass, eslint prints no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/client.ts frontend/src/pages/Review.tsx frontend/src/pages/Review.test.tsx docs/phase1-acceptance.md
git commit -m "feat(frontend): Review lists practised sentences not in Anki; Phase 1.5 acceptance items"
```

---

## Rulings on spec ambiguities

- **Cue "Done — Enter for next" (§6.2):** in Echo and Chorus, Enter records again and → moves on; the cue names the real keys ("Done — → for the next sentence, Enter to try again"). Flow's done cue is "Done — Enter to run it again" (Enter re-runs the range). Changing Enter to mean "next" would break the existing Echo flow.
- **Echo count-in vs "ghost wipe from the moment recording starts" (§6.5):** the mic starts capturing on Enter as before (no delay, VAD unchanged); the 1.5 s count-in runs over the first 1.5 s of the recording and the ghost wipe starts when it ends.
- **"Omitted when the preceding gap is shorter than 0.5 s":** applied to Flow along (the silence between the previous line's speech and the next line's); in after and Echo nothing precedes the turn but the reference itself, so the count-in always shows.
- **Text hidden while recording (default on) vs ghost wipe:** with the text hidden the wipes run over a row of blank cells (one per syllable) instead of the hidden sentence.
- **Error cue text:** the cue says "Something went wrong — see the message below" and the message stays in the transport's alert, so it is not shown twice.
- **Subtitle languages:** `zh-CN` and `zh-HK` (the regional names YouTube uses for the same scripts) are accepted next to `zh-Hans` and `zh-Hant`/`zh-TW`.
- **Chapters on a lesson under 4 minutes:** one passage (the 4-minute rule wins over chapters).
- **A failed YouTube lesson added again:** the failed lesson is deleted and a new one (new id) is created and ingested.
- **"In-app navigation away (library link, lesson switch)":** the Practice page has no lesson switcher; its only in-app exit is the ← link, which is intercepted. Browser Back is not intercepted (`useBlocker` needs a data router; the app uses `<BrowserRouter>`); like closing the tab, it is covered by Review → Practised, not in Anki.
- **Duplicate notes in a bulk send:** `exportToAnki` keeps asking per duplicate (existing behaviour).
- **Anki gap fill confidence:** spans filled from the gap are recorded with conf 0.5 like other repaired spans.

## Ledger

Filled in by the controller during execution.

- Task 3, aligner comparison on lesson 1 (date, output table, verdict, decision):
