import { describe, expect, it } from 'vitest'
import { speechBounds } from './speech'

// `n` buckets of a quiet floor with buckets lo..hi (inclusive) loud.
const peaksWith = (n: number, lo: number, hi: number, loud = 0.5, floor = 0.001) =>
  Float32Array.from({ length: n }, (_, b) => (b >= lo && b <= hi ? loud : floor))

describe('speechBounds', () => {
  it('bounds the loud part with padding', () => {
    const b = speechBounds(peaksWith(100, 20, 60), 2.0)!
    expect(b.from).toBeCloseTo(0.25, 5)
    expect(b.to).toBeCloseTo(1.37, 5)
  })
  it('null for silence', () => {
    expect(speechBounds(new Float32Array(100), 2.0)).toBeNull()
    expect(speechBounds(new Float32Array(0), 2.0)).toBeNull()
  })
  it('clamps to the take', () => {
    expect(speechBounds(peaksWith(100, 0, 99), 2.0)).toEqual({ from: 0, to: 2.0 })
    const b = speechBounds(peaksWith(100, 2, 97), 2.0)!
    expect(b.from).toBe(0)
    expect(b.to).toBe(2.0)
  })
  it('counts only what is within relDb of the loudest bucket as voice', () => {
    const p = peaksWith(100, 40, 50)
    p[10] = 0.5 * 10 ** (-40 / 20)                    // a breath 40 dB down: not voice at -35
    p[80] = 0.5 * 10 ** (-30 / 20)                    // 30 dB down: voice
    const b = speechBounds(p, 2.0, { padS: 0 })!
    expect(b.from).toBeCloseTo(0.8, 5)
    expect(b.to).toBeCloseTo(1.62, 5)
    expect(speechBounds(p, 2.0, { relDb: -45, padS: 0 })!.from).toBeCloseTo(0.2, 5)
  })
})
