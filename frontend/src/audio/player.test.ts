import { describe, it, expect } from 'vitest'
import { peaks } from './player'

describe('peaks', () => {
  it('returns max abs per bucket', () => {
    const s = new Float32Array([0.1, -0.5, 0.2, 0.9, 0.0, -0.3])
    const result = peaks(s, 3)
    expect(result[0]).toBeCloseTo(0.5, 5)
    expect(result[1]).toBeCloseTo(0.9, 5)
    expect(result[2]).toBeCloseTo(0.3, 5)
  })
  it('handles fewer samples than buckets', () => {
    expect(peaks(new Float32Array([0.4]), 4).length).toBe(4)
  })
})
