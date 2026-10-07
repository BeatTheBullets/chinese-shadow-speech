import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import type { LessonDetail, Segment } from '../api/types'
import { currentTake, usePractice } from './practice'

const take = (url: string, id = 0) => ({ id, url, duration: 1, peaks: null })

describe('practice store', () => {
  const original = URL.revokeObjectURL
  let revoke: ReturnType<typeof vi.fn>
  beforeEach(() => {
    revoke = vi.fn(); URL.revokeObjectURL = revoke as typeof URL.revokeObjectURL
    usePractice.setState({ idx: 0, attemptsThisSegment: 0, lastAttempt: null, hint: '', storedTakes: {} })
  })
  afterEach(() => { URL.revokeObjectURL = original })

  it('moving to another sentence resets per-sentence state and frees the take', () => {
    const s = usePractice.getState()
    s.setLastAttempt(take('blob:a')); s.bumpAttempts(); s.setHint('move on')
    usePractice.getState().setIdx(3)
    const after = usePractice.getState()
    expect(after).toMatchObject({ idx: 3, attemptsThisSegment: 0, lastAttempt: null, hint: '' })
    expect(revoke).toHaveBeenCalledWith('blob:a')
  })
  it('updating the same take (upload id arrives) keeps its URL alive; a new take frees the old one', () => {
    const s = usePractice.getState()
    s.setLastAttempt(take('blob:a'))
    s.setLastAttempt(take('blob:a', 9))
    expect(revoke).not.toHaveBeenCalled()
    expect(usePractice.getState().lastAttempt?.id).toBe(9)
    s.setLastAttempt(take('blob:b'))
    expect(revoke).toHaveBeenCalledWith('blob:a')
  })

  describe('the take R replays', () => {
    const seg = (id: number, idx: number) => ({ id, idx }) as Segment
    const lesson = { id: 1, segments: [seg(11, 0), seg(12, 1)] } as LessonDetail
    const stored = (id: number) => ({ id, url: `/att/${id}`, duration: 2 })
    beforeEach(() => { usePractice.setState({ lesson }) })

    it('is none without a take of the current sentence', () => {
      usePractice.getState().setStoredTakes({ 12: stored(5) })
      expect(currentTake(usePractice.getState())).toBeNull()
    })
    it("is the sentence's stored take when nothing was recorded this visit", () => {
      usePractice.getState().setStoredTakes({ 11: stored(5) })
      expect(currentTake(usePractice.getState())).toEqual(stored(5))
    })
    it("is this visit's take while its upload is pending or once it is at least as new as the stored one", () => {
      const s = usePractice.getState()
      s.setStoredTakes({ 11: stored(5) })
      s.setLastAttempt(take('blob:a'))
      expect(currentTake(usePractice.getState())).toMatchObject({ url: 'blob:a' })
      s.setLastAttempt(take('blob:a', 6)); s.recordTake(11, stored(6))
      expect(currentTake(usePractice.getState())).toMatchObject({ url: 'blob:a' })
    })
    it('is the stored take when it is newer than this visit\'s (e.g. a Flow run since)', () => {
      const s = usePractice.getState()
      s.setLastAttempt(take('blob:a', 6)); s.recordTake(11, stored(9))
      expect(currentTake(usePractice.getState())).toEqual(stored(9))
    })
    it('loaded takes merge in: a newer take recorded meanwhile, or one the answer lacks, is kept', () => {
      const s = usePractice.getState()
      s.setStoredTakes({ 11: stored(5), 12: stored(8) })
      s.recordTake(11, stored(9))
      s.setStoredTakes({ 11: stored(7), 13: stored(3) })
      expect(usePractice.getState().storedTakes).toEqual({ 11: stored(9), 12: stored(8), 13: stored(3) })
      s.setStoredTakes({ 12: stored(10) })
      expect(usePractice.getState().storedTakes[12]).toEqual(stored(10))
    })
    it('a new lesson starts with no stored takes', () => {
      usePractice.getState().setStoredTakes({ 11: stored(5) })
      usePractice.getState().setLesson(lesson)
      expect(usePractice.getState().storedTakes).toEqual({})
    })
  })
})
