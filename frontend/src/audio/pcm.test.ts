import { describe, it, expect } from 'vitest'
import { concat, downsample, encodeWav16, findSilenceEnd, rms } from './pcm'

// jsdom's Blob has no arrayBuffer()
const readBlob = (b: Blob) => new Promise<ArrayBuffer>((res, rej) => {
  const r = new FileReader()
  r.onload = () => res(r.result as ArrayBuffer); r.onerror = () => rej(r.error); r.readAsArrayBuffer(b)
})

describe('pcm', () => {
  it('concat', () => { expect([...concat([new Float32Array([1, 2]), new Float32Array([3])])]).toEqual([1, 2, 3]) })
  it('downsample 48k→16k averages triples', () => {
    const x = new Float32Array([0.3, 0.3, 0.3, 0.6, 0.6, 0.6])
    const y = downsample(x, 48000, 16000)
    expect(y.length).toBe(2); expect(y[0]).toBeCloseTo(0.3); expect(y[1]).toBeCloseTo(0.6)
  })
  it('encodeWav16 writes a valid header', async () => {
    const blob = encodeWav16(new Float32Array([0, 0.5, -0.5]), 16000)
    const dv = new DataView(await readBlob(blob))
    expect(String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3))).toBe('RIFF')
    expect(dv.getUint32(24, true)).toBe(16000); expect(dv.getUint16(22, true)).toBe(1); expect(dv.getUint16(34, true)).toBe(16)
    expect(dv.getUint32(40, true)).toBe(6); expect(dv.getInt16(46, true)).toBe(16383)
  })
  it('findSilenceEnd detects speech then 1.2 s of silence', () => {
    const sr = 16000
    const speech = Float32Array.from({ length: sr }, (_, i) => 0.2 * Math.sin(i / 10))
    const silence = new Float32Array(sr * 1.5)
    const x = concat([new Float32Array(sr * 0.5), speech, silence])
    const idx = findSilenceEnd(x, sr)
    expect(idx).not.toBeNull(); expect(idx!).toBeGreaterThanOrEqual(sr * 1.5); expect(idx!).toBeLessThan(sr * 2.9)
    expect(findSilenceEnd(concat([new Float32Array(sr * 0.5), speech]), sr)).toBeNull()
    expect(findSilenceEnd(new Float32Array(sr * 3), sr)).toBeNull()      // never spoke
    expect(rms(new Float32Array([0.5, -0.5]))).toBeCloseTo(0.5)
  })
})
