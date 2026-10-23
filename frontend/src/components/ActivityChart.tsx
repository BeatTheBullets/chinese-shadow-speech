import { useState } from 'react'
import type { ActivityStats } from '../api/types'
import { activityBars } from '../lib/stats'
import { TOKENS } from '../theme/tokens'

const plural = (n: number) => `${n} attempt${n === 1 ? '' : 's'}`

// One series (minutes per day), so one hue: the theme's reference blue, thin bars with a rounded data end, recessive
// axis. Attempts are printed under each bar rather than encoded as a second scale. Hover a bar for its exact values.
export default function ActivityChart({ days }: { days: ActivityStats['days'] }) {
  const bars = activityBars(days)
  const max = Math.max(1, ...bars.map((b) => b.minutes))
  const W = 720, H = 160, top = 8, plotH = H - top - 34, slot = W / Math.max(1, bars.length), bw = Math.min(14, slot - 6)
  const [hover, setHover] = useState<number | null>(null)
  if (!bars.length || bars.every((b) => !b.minutes && !b.attempts)) return <p className="text-sm text-fgdim">No practice yet.</p>
  const h = hover != null ? bars[hover] : null
  return (
    <div>
      <p className="text-sm text-fgdim h-5">{h ? `${days[hover!].date} · ${h.minutes} min · ${plural(h.attempts)}` : 'Minutes per day, attempts below each bar'}</p>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Minutes practised per day, last 30 days">
        <line x1="0" x2={W} y1={top + plotH} y2={top + plotH} stroke={TOKENS.line} />
        <line x1="0" x2={W} y1={top} y2={top} stroke={TOKENS.line} strokeDasharray="2 4" />
        <text x="0" y={top - 1} fontSize="9" fill={TOKENS.fgdim}>{max} min</text>
        {bars.map((b, i) => {
          const x = i * slot + (slot - bw) / 2, bh = b.minutes ? Math.max(2, (b.minutes / max) * plotH) : 0
          return (
            <g key={days[i].date} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={i * slot} y={0} width={slot} height={H} fill="transparent" />
              {bh > 0 && <path d={`M${x},${top + plotH} V${top + Math.min(4, bh) + plotH - bh} q0,-${Math.min(4, bh)} ${Math.min(4, bh)},-${Math.min(4, bh)} H${x + bw - Math.min(4, bh)} q${Math.min(4, bh)},0 ${Math.min(4, bh)},${Math.min(4, bh)} V${top + plotH} Z`} fill={hover === i ? TOKENS.fg : TOKENS.ref} />}
              <text x={x + bw / 2} y={top + plotH + 12} fontSize="9" textAnchor="middle" fill={TOKENS.fgdim}>{b.label}</text>
              <text x={x + bw / 2} y={top + plotH + 26} fontSize="9" textAnchor="middle" fill={TOKENS.fg}>{b.attempts || ''}</text>
              <title>{`${days[i].date}: ${b.minutes} min, ${plural(b.attempts)}`}</title>
            </g>)
        })}
      </svg>
      <details className="text-sm text-fgdim mt-2"><summary className="cursor-pointer">Table</summary>
        <table className="mt-1"><thead><tr><th className="text-left pr-4">Day</th><th className="text-right pr-4">Min</th><th className="text-right">Attempts</th></tr></thead>
          <tbody>{days.map((d, i) => ({ d, b: bars[i] })).reverse().filter(({ b }) => b.minutes || b.attempts).map(({ d, b }) => <tr key={d.date}><td className="pr-4">{d.date}</td><td className="text-right pr-4">{b.minutes}</td><td className="text-right">{b.attempts}</td></tr>)}</tbody></table>
      </details>
    </div>
  )
}
