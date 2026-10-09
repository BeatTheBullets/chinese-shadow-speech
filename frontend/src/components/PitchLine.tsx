import { pathOf, type Pt } from '../lib/pitch'

interface Props { series: { points: Pt[]; className: string }[]; pxPerSec: number; duration: number; height: number; range: [number, number] }
export default function PitchLine({ series, pxPerSec, duration, height, range }: Props) {
  const width = Math.max(1, Math.round(duration * pxPerSec))
  return (
    <svg data-testid="pitch-line" className="absolute left-0 top-0 pointer-events-none" width={width} height={height} aria-hidden>
      {series.map((s, i) => <path key={i} d={pathOf(s.points, pxPerSec, height, range)} className={s.className} fill="none" strokeWidth={2} strokeLinecap="round" />)}
    </svg>
  )
}
