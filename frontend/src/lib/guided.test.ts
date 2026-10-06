import { describe, it, expect } from 'vitest'
import { nextGuidedStep, guidedText } from './guided'
describe('guided', () => {
  it('progresses listen → whisper → record → null', () => {
    expect(nextGuidedStep('listen')).toBe('whisper'); expect(nextGuidedStep('whisper')).toBe('record'); expect(nextGuidedStep('record')).toBeNull()
  })
  it('hides text only when recording', () => { expect(guidedText('whisper').showText).toBe(true); expect(guidedText('record').showText).toBe(false) })
})
