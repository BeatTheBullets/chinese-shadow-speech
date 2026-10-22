import { describe, expect, it } from 'vitest'
import { charFill, clipSpans, countInDots, countInWindow, flowWipe, ghostProgress, lineLead, nextLineStart, stageWipe, wipeProgress, type ClipSpan } from './karaoke'
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

describe('stageWipe (Echo, Drill)', () => {
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
  it('along: the count-in carries on into the lead silence of the new line, down to its first syllable', () => {
    const lead = { at: 0.6, gap: 0.8 } // 0.6 s of silence at the start of the clip
    expect(flowWipe({ ...base, sub: 'along', clipTime: 0, lead }).dots).toBe(2)
    expect(flowWipe({ ...base, sub: 'along', clipTime: 0.3, lead }).dots).toBe(1)
    expect(flowWipe({ ...base, sub: 'along', clipTime: 0.6, lead }).dots).toBe(0)
    expect(flowWipe({ ...base, sub: 'along', clipTime: 0, lead: { at: 0.6, gap: 0.3 } }).dots).toBe(0) // no real pause: none
    expect(flowWipe({ ...base, sub: 'along', clipTime: 0, lead, rate: 0.5 }).dots).toBe(2) // 1.2 s real time left
  })
  it('lineLead: when the line speaks within its own clip, and the silence before it', () => {
    const prev = { start_s: 10, end_s: 12, ref_alignment_json: [{ ch: '你', start: 10.2, end: 11.5, conf: 1 }] }
    const cur = { start_s: 12, end_s: 14, ref_alignment_json: [{ ch: '好', start: 12.6, end: 13, conf: 1 }] }
    const a = lineLead(prev, cur, 0.5)
    expect(a.at).toBeCloseTo(1.2); expect(a.gap).toBeCloseTo(2.2)
  })
  it('nothing playing: nothing to draw', () => {
    expect(flowWipe({ ...base, sub: 'after', clipTime: null })).toEqual({ wipe: null, dots: 0, turnLeft: null })
  })
})

describe('null and empty alignment never throws', () => {
  it('helpers degrade to no wipe', () => {
    const none = null as unknown as ClipSpan[]
    expect(wipeProgress(none, 1)).toBe(0)
    expect(ghostProgress(none, 1, 1)).toBe(0)
    expect(stageWipe({ spans: none, refPlaying: true, refHead: 0.5, turnStart: null, now: 0, rate: 1 })).toEqual({ wipe: null, dots: 0 })
    expect(stageWipe({ spans: [], refPlaying: false, refHead: null, turnStart: 1, now: 3, rate: 1 })).toEqual({ wipe: null, dots: 0 })
    expect(flowWipe({ spans: none, sub: 'after', clipTime: 0.5, clipDuration: 2, turn: { startedAt: 0, duration: 2 }, now: 1, rate: 1, next: null }).wipe).toBeNull()
    expect(flowWipe({ spans: [], sub: 'after', clipTime: 0.5, clipDuration: 2, turn: null, now: 0, rate: 1, next: null }).wipe).toBeNull()
    expect(charFill('', 1)).toEqual([])
  })
})
