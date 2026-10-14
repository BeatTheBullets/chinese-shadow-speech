import { useState } from 'react'
import type { ToneStats } from '../api/types'
import { TONE_NAMES, pct } from '../lib/score'

// Categorical slots 1-5 of the dataviz dark palette in fixed order, one per tone (neutral last); validated on the dark surface.
const TONES = [1, 2, 3, 4, 0]
const COLOR: Record<number, string> = { 1: '#3987e5', 2: '#d95926', 3: '#199e70', 4: '#c98500', 0: '#d55181' }
const label = (t: number) => (t === 0 ? 'Neutral' : `Tone ${t} · ${TONE_NAMES[t]}`)

// One thin line per tone over the weeks on a fixed 0-100 scale; a week without a score for a tone leaves a gap.
// Hover a point for its exact value; the legend and the table keep identity from resting on colour alone.
export default function ToneTrend({ weeks }: { weeks: ToneStats['weeks'] }) {
  const [hover, setHover] = useState<string | null>(null)
  const names = [...new Set(weeks.map((w) => w.week))].sort()
  if (!names.length) return <p className="text-sm text-fgdim">No weekly scores yet.</p>
  const W = 720, H = 160, left = 28, top = 8, plotH = H - top - 20, plotW = W - left - 8
  const x = (i: number) => left + (names.length === 1 ? plotW / 2 : (i / (names.length - 1)) * plotW)
  const y = (m: number) => top + (1 - m) * plotH
  const by = new Map(weeks.map((w) => [`${w.tone}|${w.week}`, w]))
  const lines = TONES.map((t) => ({ t, pts: names.map((wk, i) => ({ i, wk, w: by.get(`${t}|${wk}`) })) })).filter((l) => l.pts.some((p) => p.w))
  const d = (pts: typeof lines[number]['pts']) => pts.map((p, k) => (p.w ? `${k > 0 && pts[k - 1].w ? 'L' : 'M'}${x(p.i)},${y(p.w.mean)}` : '')).join(' ')
  return (
    <div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-fgdim">
        {lines.map(({ t }) => <span key={t} className="flex items-center gap-1"><svg width="10" height="10" aria-hidden="true"><circle cx="5" cy="5" r="4" fill={COLOR[t]} /></svg>{label(t)}</span>)}
      </div>
      <p className="text-sm text-fgdim h-5">{hover ?? 'Mean score per tone, by week'}</p>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full" role="img" aria-label="Tone scores per week, last 12 weeks">
        <line x1={left} x2={W} y1={top + plotH} y2={top + plotH} stroke="#2a3139" />
        <line x1={left} x2={W} y1={top} y2={top} stroke="#2a3139" strokeDasharray="2 4" />
        <text x="0" y={top + 3} fontSize="9" fill="#7c8793">100</text>
        <text x="0" y={top + plotH} fontSize="9" fill="#7c8793">0</text>
        {names.map((wk, i) => (i === 0 || i === names.length - 1 || i % 2 === 0) && <text key={wk} x={x(i)} y={H - 4} fontSize="9" textAnchor="middle" fill="#7c8793">{wk.slice(-3)}</text>)}
        {lines.map(({ t, pts }) => (
          <g key={t}>
            <path d={d(pts)} fill="none" stroke={COLOR[t]} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
            {pts.filter((p) => p.w).map((p) => {
              const tip = `${label(t)} · ${p.wk} · ${pct(p.w!.mean)} (n ${p.w!.n})`
              return (
                <g key={p.wk} onMouseEnter={() => setHover(tip)} onMouseLeave={() => setHover(null)}>
                  <circle cx={x(p.i)} cy={y(p.w!.mean)} r="12" fill="transparent" />
                  <circle cx={x(p.i)} cy={y(p.w!.mean)} r="4" fill={COLOR[t]} stroke="#111418" strokeWidth="2" />
                  <title>{tip}</title>
                </g>)
            })}
          </g>))}
      </svg>
      <details className="text-sm text-fgdim mt-2"><summary className="cursor-pointer">Table</summary>
        <table className="mt-1"><thead><tr><th className="text-left pr-4">Week</th>{lines.map(({ t }) => <th key={t} className="text-right pr-4 font-normal">{label(t)}</th>)}</tr></thead>
          <tbody>{[...names].reverse().map((wk) => <tr key={wk}><td className="pr-4">{wk}</td>{lines.map(({ t }) => <td key={t} className="text-right pr-4">{pct(by.get(`${t}|${wk}`)?.mean)}</td>)}</tr>)}</tbody></table>
      </details>
    </div>
  )
}
