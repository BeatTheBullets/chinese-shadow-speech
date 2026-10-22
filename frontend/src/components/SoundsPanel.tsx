import type { SoundStats } from '../api/types'
import { TOKENS } from '../theme/tokens'

// Weekly slip rate for one sound as a tiny line; 0..1 on the y axis so lines compare across rows. Needs two weeks to be a trend.
function Spark({ label, rates }: { label: string; rates: number[] }) {
  if (rates.length < 2) return null
  const W = 60, H = 16, step = W / (rates.length - 1)
  const pts = rates.map((r, i) => `${(i * step).toFixed(1)},${(H - 1 - Math.min(1, Math.max(0, r)) * (H - 2)).toFixed(1)}`).join(' ')
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={W} height={H} role="img" aria-label={`${label} slip rate per week`}>
      <polyline points={pts} fill="none" stroke={TOKENS.ref} strokeWidth="1.5" />
    </svg>)
}

export default function SoundsPanel({ stats, onDrill }: { stats: SoundStats; onDrill: (key: string) => void }) {
  if (!stats.sounds.length) return <p className="text-sm text-fgdim">No sound results yet.</p>
  return (
    <>{stats.sounds.map((s) => (
      <div key={s.key} className="border-b border-line py-1 flex gap-4 items-center">
        <span>{s.label}</span><span className="text-fgdim">{s.slips} of {s.chances}</span><span>{Math.round(s.rate * 100)}%</span>
        <Spark label={s.label} rates={stats.weeks.filter((w) => w.key === s.key).sort((a, b) => a.week.localeCompare(b.week)).map((w) => w.rate)} />
        <button type="button" className="text-xs text-accent ml-auto" aria-label={`Drill ${s.label}`} onClick={() => onDrill(s.key)}>Drill this</button>
      </div>))}</>
  )
}
