import { useEffect, useState } from 'react'
import { rms } from '../audio/pcm'
import type { Mic } from '../audio/useMic'

export const WAVE_MS = 50                                    // ~20 updates per second, as the old mic meter
export const WAVE_BARS = 80                                  // LIVE_WINDOW_S (1.6 s) in 20 ms frames, one bar each
const GAIN = 5                                               // speech RMS of ~0.02–0.2 spans most of the height
const FLAT = 4                                               // % of the height: silence is a flat line, not nothing

// Bar heights (whole % of the height, so an unchanged picture compares equal) of the newest WAVE_BARS frames;
// the window always spans LIVE_WINDOW_S (Mic.snapshot pads it), so each frame is 20 ms. Newest on the right.
function barsOf(x: Float32Array): number[] {
  const frame = Math.floor(x.length / WAVE_BARS)
  if (!frame) return []
  const off = x.length - frame * WAVE_BARS
  return Array.from({ length: WAVE_BARS }, (_, i) =>
    Math.max(FLAT, Math.round(Math.min(1, rms(x.subarray(off + i * frame, off + (i + 1) * frame)) * GAIN) * 100)))
}
const same = (a: number[], b: number[]) => a.length === b.length && a.every((v, i) => v === b[i])

// Your voice while you speak (spec §3): rounded bars that grow as you speak and lie flat in silence — the mic check
// that replaced the level meter. Polls the mic itself, so only this re-renders and not the page around it.
export default function LiveWave({ mic, color }: { mic: Pick<Mic, 'snapshot'>; color: string }) {
  const [bars, setBars] = useState<number[]>([])
  useEffect(() => {
    const t = window.setInterval(() => {
      const s = mic.snapshot()
      const next = s ? barsOf(s) : []
      setBars((p) => (same(p, next) ? p : next))
    }, WAVE_MS)
    return () => window.clearInterval(t)
  }, [mic])
  return (
    <div data-testid="live-wave" role="img" aria-label="Your voice, live" className="flex items-center justify-center gap-0.5 h-12">
      {bars.map((h, i) => <span key={i} data-testid="wave-bar" className="block w-1 rounded-full" style={{ height: `${h}%`, backgroundColor: color }} />)}
    </div>
  )
}
