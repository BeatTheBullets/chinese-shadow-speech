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
