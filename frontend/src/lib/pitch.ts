import type { Contour } from '../api/types'

// A pitch point: time (s) on the track's own axis and normalised pitch (spec §5.1), null where unvoiced.
export type Pt = [number, number | null]

export function contourPoints(c: Contour): Pt[] {
  return c.f0_st.map((v, i) => [c.t0_s + (i * c.step_ms) / 1000, v])
}

// The reference curve drawn faintly behind yours (spec §6): each reference syllable's frames are stretched onto your
// span of the same syllable, so the two curves line up syllable by syllable even when your timing differs.
export function warpPoints(ref: Contour, targetSpans: [number, number][]): Pt[] {
  const pts = contourPoints(ref), out: Pt[] = []
  ref.spans.forEach(([rs, re], i) => {
    const target = targetSpans[i]
    if (!target || re <= rs) return
    const [ts, te] = target
    if (out.length) out.push([ts, null])
    for (const [t, v] of pts) if (t >= rs && t <= re) out.push([ts + ((t - rs) / (re - rs)) * (te - ts), v])
  })
  return out
}

export function pitchRange(...series: Pt[][]): [number, number] {
  const vals = series.flat().map(([, v]) => v).filter((v): v is number => v != null && Number.isFinite(v))
  if (!vals.length) return [-1, 1]
  let lo = Math.min(...vals), hi = Math.max(...vals)
  if (hi - lo < 2) { const m = (hi + lo) / 2; lo = m - 1; hi = m + 1; return [lo, hi] }
  const pad = (hi - lo) * 0.1
  return [lo - pad, hi + pad]
}

export function pathOf(points: Pt[], pxPerSec: number, height: number, [lo, hi]: [number, number]): string {
  let d = '', pen = false
  for (const [t, v] of points) {
    if (v == null) { pen = false; continue }
    const x = (t * pxPerSec).toFixed(1), y = (height - ((v - lo) / (hi - lo)) * height).toFixed(1)
    d += `${pen ? 'L' : 'M'}${x},${y}`; pen = true
  }
  return d
}
