import { describe, expect, it } from 'vitest'
import type { AlignSpan } from '../api/types'
import { SPEECH_MARGIN_S, SPAN_TAIL_S, refWindow, sliceToWindow, speechWindow } from './timeline'

// `n` buckets of a quiet floor with buckets lo..hi (inclusive) loud.
const peaksWith = (n: number, lo: number, hi: number) => Float32Array.from({ length: n }, (_, b) => (b >= lo && b <= hi ? 0.5 : 0.001))

describe('speechWindow', () => {
  it('the reference: first syllable start to last syllable end (clip-relative), plus the margin each side', () => {
    const w = speechWindow(2, [[0.5, 0.8], [0.8, 1.1], [1.1, 1.6]])!
    expect(SPEECH_MARGIN_S).toBe(0.1)
    expect(w.from).toBeCloseTo(0.4, 6); expect(w.to).toBeCloseTo(1.7, 6); expect(w.speech).toBeCloseTo(1.1, 6)
  })
  it('a scored take: from the score spans on the raw take timeline, ignoring the peaks', () => {
    const w = speechWindow(4.9, [[1.8, 2.2], [2.2, 2.7], [2.7, 3.1]], peaksWith(100, 0, 99))!
    expect(w.from).toBeCloseTo(1.7, 6); expect(w.to).toBeCloseTo(3.2, 6); expect(w.speech).toBeCloseTo(1.3, 6)
  })
  it('a take before scoring: from the loud peaks, without speechBounds’ playback padding', () => {
    // 100 buckets over 2 s: buckets 20..60 loud = 0.4 … 1.22 s
    const w = speechWindow(2, null, peaksWith(100, 20, 60))!
    expect(w.from).toBeCloseTo(0.3, 6); expect(w.to).toBeCloseTo(1.32, 6); expect(w.speech).toBeCloseTo(0.82, 6)
    expect(speechWindow(2, [], peaksWith(100, 20, 60))!.from).toBeCloseTo(0.3, 6) // no spans counts as unscored
  })
  it('clamps the margin to the clip', () => {
    const w = speechWindow(1.2, [[0.05, 0.6], [0.6, 1.15]])!
    expect(w.from).toBe(0); expect(w.to).toBe(1.2); expect(w.speech).toBeCloseTo(1.1, 6)
  })
  it('the whole clip when there is nothing to go by; null without a clip', () => {
    expect(speechWindow(2, null, null)).toEqual({ from: 0, to: 2, speech: 2 })
    expect(speechWindow(2, null, new Float32Array(50))).toEqual({ from: 0, to: 2, speech: 2 }) // all silent
    expect(speechWindow(0, [[0, 1]])).toBeNull()
  })
})

describe('refWindow', () => {
  // Source-absolute alignment, clip from 10 s (2 s long): raw CTC spans, ending about half-way through each syllable.
  const align = (pairs: [number, number][]): AlignSpan[] => pairs.map(([start, end]) => ({ ch: 'x', start, end, conf: 1 }))
  const a = align([[10.5, 10.8], [10.8, 11.1], [11.1, 11.45]])
  it('unscored: the alignment made clip-relative, its last end extended by the scorer’s window tail', () => {
    expect(SPAN_TAIL_S).toBe(0.15)
    const w = refWindow(2, a, 10, null, null)!
    expect(w.from).toBeCloseTo(0.4, 6); expect(w.to).toBeCloseTo(1.7, 6); expect(w.speech).toBeCloseTo(1.1, 6) // 0.5 … 1.6
  })
  it('the tail stops at the clip end', () => {
    const w = refWindow(1.5, a, 10, null, null)!
    expect(w.to).toBe(1.5); expect(w.speech).toBeCloseTo(1.0, 6)    // 0.5 … 1.5
  })
  it('scored: the score’s reference windows (the same rule as your take), not the raw alignment', () => {
    const w = refWindow(2, a, 10, [[0.5, 0.8], [0.8, 1.1], [1.1, 1.62]], null)!
    expect(w.from).toBeCloseTo(0.4, 6); expect(w.to).toBeCloseTo(1.72, 6); expect(w.speech).toBeCloseTo(1.12, 6)
  })
  it('no alignment: from the peaks, else the whole clip', () => {
    expect(refWindow(2, null, 10, null, peaksWith(100, 20, 60))!.from).toBeCloseTo(0.3, 6)
    expect(refWindow(2, [], 10, null, null)).toEqual({ from: 0, to: 2, speech: 2 })
  })
})

describe('sliceToWindow', () => {
  it('keeps the window’s buckets and snaps the window out to their edges', () => {
    const peaks = Float32Array.from({ length: 10 }, (_, i) => i) // 10 buckets over 2 s: 0.2 s each
    const s = sliceToWindow(peaks, 2, { from: 0.5, to: 1.3, speech: 0.6 })
    expect([...s.peaks!]).toEqual([2, 3, 4, 5, 6])                //  buckets covering 0.4 … 1.4
    expect(s.from).toBeCloseTo(0.4, 6); expect(s.to).toBeCloseTo(1.4, 6)
  })
  it('no peaks: the window as it is', () => {
    expect(sliceToWindow(null, 2, { from: 0.5, to: 1.3, speech: 0.6 })).toEqual({ peaks: null, from: 0.5, to: 1.3 })
  })
})
