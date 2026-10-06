import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { usePractice } from './practice'

const take = (url: string, id = 0) => ({ id, url, duration: 1, peaks: null })

describe('practice store', () => {
  const original = URL.revokeObjectURL
  let revoke: ReturnType<typeof vi.fn>
  beforeEach(() => {
    revoke = vi.fn(); URL.revokeObjectURL = revoke as typeof URL.revokeObjectURL
    usePractice.setState({ idx: 0, attemptsThisSegment: 0, lastAttempt: null, hint: '' })
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
})
