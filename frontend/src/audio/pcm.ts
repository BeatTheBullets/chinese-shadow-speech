export function concat(chunks: Float32Array[]): Float32Array {
  const out = new Float32Array(chunks.reduce((n, c) => n + c.length, 0))
  let o = 0
  for (const c of chunks) { out.set(c, o); o += c.length }
  return out
}

export function downsample(x: Float32Array, fromSr: number, toSr = 16000): Float32Array {
  if (fromSr === toSr) return x
  const ratio = fromSr / toSr
  const n = Math.floor(x.length / ratio)
  const out = new Float32Array(n)
  for (let i = 0; i < n; i++) {
    const a = Math.floor(i * ratio), z = Math.min(x.length, Math.floor((i + 1) * ratio))
    let s = 0
    for (let j = a; j < z; j++) s += x[j]
    out[i] = s / Math.max(1, z - a)
  }
  return out
}

export function encodeWav16(x: Float32Array, sr: number): Blob {
  const buf = new ArrayBuffer(44 + x.length * 2)
  const dv = new DataView(buf)
  const str = (o: number, s: string) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)) }
  str(0, 'RIFF'); dv.setUint32(4, 36 + x.length * 2, true); str(8, 'WAVE'); str(12, 'fmt ')
  dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true); dv.setUint32(24, sr, true)
  dv.setUint32(28, sr * 2, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true); str(36, 'data'); dv.setUint32(40, x.length * 2, true)
  for (let i = 0; i < x.length; i++) { const v = Math.max(-1, Math.min(1, x[i])); dv.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true) }
  return new Blob([buf], { type: 'audio/wav' })
}

export function rms(x: Float32Array): number {
  let s = 0
  for (let i = 0; i < x.length; i++) s += x[i] * x[i]
  return Math.sqrt(s / Math.max(1, x.length))
}

export interface VadOpts { threshold: number; holdMs: number; minSpeechMs: number }
export function findSilenceEnd(x: Float32Array, sr: number, opts: VadOpts = { threshold: 0.01, holdMs: 1200, minSpeechMs: 300 }): number | null {
  const frame = Math.floor(sr * 0.02)
  let speechFrames = 0, silentFrames = 0, spoke = false, lastSpeechEnd = -1
  const needSpeech = Math.ceil(opts.minSpeechMs / 20), needSilence = Math.ceil(opts.holdMs / 20)
  for (let a = 0; a + frame <= x.length; a += frame) {
    if (rms(x.subarray(a, a + frame)) > opts.threshold) { speechFrames++; silentFrames = 0; if (speechFrames >= needSpeech) { spoke = true; lastSpeechEnd = a + frame } }
    else { silentFrames++; if (spoke && silentFrames >= needSilence) return lastSpeechEnd }
  }
  return null
}
