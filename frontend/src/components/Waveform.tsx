import { useEffect, useMemo, useRef } from 'react'
import { normalizePeaks } from '../lib/timeline'
import { TOKENS } from '../theme/tokens'
interface Props { peaks: Float32Array | null; duration: number; pxPerSec: number; ticks?: number[]; playhead?: number | null; color: string; height?: number }
export default function Waveform({ peaks, duration, pxPerSec, ticks = [], playhead, color, height = 44 }: Props) {
  const ref = useRef<HTMLCanvasElement>(null)
  // Each track at its own loudness: the loudest bar is full height, whatever the clip's level (mic vs clip).
  const bars = useMemo(() => normalizePeaks(peaks), [peaks])
  useEffect(() => {
    const c = ref.current; if (!c) return
    const w = Math.max(1, Math.round(duration * pxPerSec)); c.width = w; c.height = height
    const g = c.getContext('2d'); if (!g) return
    g.clearRect(0, 0, w, height)
    // Bars fill in as they play: before the playhead full colour, after it 35 %. With no playhead everything is "played".
    if (bars) {
      const bw = w / bars.length, barW = Math.max(1, bw - 1), r = barW / 2
      g.fillStyle = color
      bars.forEach((p, i) => {
        const h = Math.max(1, p * (height - 4)), x = i * bw, y = (height - h) / 2
        g.globalAlpha = playhead == null || x < playhead * pxPerSec ? 1 : 0.35
        // roundRect is missing in older browsers: square bars beat no bars.
        if (typeof g.roundRect === 'function') { g.beginPath(); g.roundRect(x, y, barW, h, Math.min(r, h / 2)); g.fill() } else g.fillRect(x, y, barW, h)
      })
    }
    // Syllable boundaries: faint ticks, not hard lines.
    g.globalAlpha = 0.5; g.strokeStyle = TOKENS.line
    ticks.forEach((t) => { const x = Math.round(t * pxPerSec) + 0.5; g.beginPath(); g.moveTo(x, 0); g.lineTo(x, height); g.stroke() })
    g.globalAlpha = 1
    if (playhead != null) { const x = Math.round(playhead * pxPerSec) + 0.5; g.strokeStyle = TOKENS.fg; g.beginPath(); g.moveTo(x, 0); g.lineTo(x, height); g.stroke() }
  }, [bars, duration, pxPerSec, ticks, playhead, color, height])
  return <canvas ref={ref} className="block" style={{ width: Math.round(duration * pxPerSec), height }} />
}
