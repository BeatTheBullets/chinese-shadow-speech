import { useEffect, useRef } from 'react'
import { TOKENS } from '../theme/tokens'
interface Props { peaks: Float32Array | null; duration: number; pxPerSec: number; ticks?: number[]; playhead?: number | null; color: string; height?: number }
export default function Waveform({ peaks, duration, pxPerSec, ticks = [], playhead, color, height = 44 }: Props) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current; if (!c) return
    const w = Math.max(1, Math.round(duration * pxPerSec)); c.width = w; c.height = height
    const g = c.getContext('2d'); if (!g) return
    g.clearRect(0, 0, w, height)
    if (peaks) { const bw = w / peaks.length; g.fillStyle = color; peaks.forEach((p, i) => { const h = Math.max(1, p * (height - 4)); g.fillRect(i * bw, (height - h) / 2, Math.max(1, bw - 1), h) }) }
    g.strokeStyle = TOKENS.line; ticks.forEach((t) => { const x = Math.round(t * pxPerSec) + 0.5; g.beginPath(); g.moveTo(x, 0); g.lineTo(x, height); g.stroke() })
    if (playhead != null) { const x = Math.round(playhead * pxPerSec) + 0.5; g.strokeStyle = TOKENS.fg; g.beginPath(); g.moveTo(x, 0); g.lineTo(x, height); g.stroke() }
  }, [peaks, duration, pxPerSec, ticks, playhead, color, height])
  return <canvas ref={ref} style={{ width: Math.round(duration * pxPerSec), height }} />
}
