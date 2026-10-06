import { describe, it, expect } from 'vitest'
import { sliceRangesFromActual, gapAfter, weakestResults } from './flow'
const A = [
  { segmentId: 1, idx: 0, playStart: 10.0, playEnd: 12.0, refDuration: 2.0 },
  { segmentId: 2, idx: 1, playStart: 14.5, playEnd: 16.0, refDuration: 1.5 },
  { segmentId: 3, idx: 2, playStart: 18.0, refDuration: 1.0 },          // interrupted
]
describe('flow slices', () => {
  it('after: gap after each clip, skips unfinished', () => {
    const r = sliceRangesFromActual(A, 'after', 1.1)
    expect(r.length).toBe(2)
    expect(r[0]).toEqual({ segmentId: 1, idx: 0, t0: 11.85, t1: 14.35 })
  })
  it('along: spans the clip itself', () => {
    expect(sliceRangesFromActual(A, 'along', 1.1)[1]).toEqual({ segmentId: 2, idx: 1, t0: 14.35, t1: 16.15 })
  })
  it('gapAfter', () => { expect(gapAfter(2, 1.1)).toBeCloseTo(2.2) })
})
describe('weakestResults', () => {
  const r = (segmentId: number) => ({ segmentId, idx: segmentId, attemptId: null, url: '', duration: 1 })
  it('returns the lowest-scored results first, ignoring unscored lines', () => {
    const scores = new Map<number, number | null>([[1, 0.9], [2, 0.4], [3, null], [4, 0.6], [5, 0.7]])
    expect(weakestResults([r(1), r(2), r(3), r(4), r(5)], scores, 3).map((x) => x.segmentId)).toEqual([2, 4, 5])
  })
  it('is empty when nothing is scored yet (Phase 1)', () => {
    expect(weakestResults([r(1), r(2)], new Map([[1, null]]), 3)).toEqual([])
  })
})
