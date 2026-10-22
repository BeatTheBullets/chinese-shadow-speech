import { Link } from 'react-router-dom'
import type { DrillSummary as Summary } from '../api/types'
import { pct } from '../lib/score'
import { TOKENS } from '../theme/tokens'
import Button from '../ui/Button'

// Two series from ToneTrend's dark palette (categorical slots 1 and 3), on its 0-100 scale and axis colours.
const SERIES = [{ key: 'first_mean', label: 'first try', color: TOKENS.ref }, { key: 'best_mean', label: 'best', color: TOKENS.ok }] as const

// The focus's last drills (oldest first): the first-try and best target mean of each, as two thin lines.
function History({ label, history }: { label: string; history: Summary['history'] }) {
  if (!history.length) return null
  const W = 360, H = 90, left = 28, top = 6, plotH = H - top - 14, plotW = W - left - 8
  const x = (i: number) => left + (history.length === 1 ? plotW / 2 : (i / (history.length - 1)) * plotW)
  const y = (m: number) => top + (1 - m) * plotH
  return (
    <div>
      <div className="flex gap-4 text-xs text-fgdim">
        {SERIES.map((s) => <span key={s.key} className="flex items-center gap-1"><svg width="10" height="10" aria-hidden="true"><circle cx="5" cy="5" r="4" fill={s.color} /></svg>{s.label}</span>)}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="w-full max-w-md" role="img" aria-label={`Drill history for ${label}`}>
        <line x1={left} x2={W} y1={top + plotH} y2={top + plotH} stroke={TOKENS.line} />
        <line x1={left} x2={W} y1={top} y2={top} stroke={TOKENS.line} strokeDasharray="2 4" />
        <text x="0" y={top + 3} fontSize="9" fill={TOKENS.fgdim}>100</text>
        <text x="0" y={top + plotH} fontSize="9" fill={TOKENS.fgdim}>0</text>
        {SERIES.map((s) => {
          const pts = history.map((h, i) => ({ i, h, m: h[s.key] }))
          const d = pts.map((p, k) => (p.m == null ? '' : `${k > 0 && pts[k - 1].m != null ? 'L' : 'M'}${x(p.i)},${y(p.m)}`)).join(' ')
          return (
            <g key={s.key}>
              <path d={d} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
              {pts.map((p) => p.m != null && (
                <circle key={p.h.session_id} cx={x(p.i)} cy={y(p.m)} r="4" fill={s.color} stroke={TOKENS.panel} strokeWidth="2">
                  <title>{`${p.h.started_at.slice(0, 10)} · ${s.label} ${pct(p.m)}`}</title>
                </circle>))}
            </g>)
        })}
      </svg>
    </div>
  )
}

// The end of a drill (spec §4): how the target syllables went from first try to best, the focus's history, and the
// sentences that never went green — to drill again, or to open in Practice. `busy`: a run is starting (one click, one run).
export default function DrillSummary({ summary: s, onAgain, onDone, busy = false }: { summary: Summary; onAgain: (segmentIds: number[]) => void; onDone: () => void; busy?: boolean }) {
  const notGreen = s.items.filter((it) => !it.went_green)
  return (
    <div className="space-y-4">
      <h1 className="text-lg text-fg font-semibold">{s.label}: target syllables first try {pct(s.first_mean)} → best {pct(s.best_mean)} · green {s.green_first} → {s.green_best} of {s.n_targets}</h1>
      <History label={s.label} history={s.history} />
      {notGreen.length ? (<>
        <h2 id="not-green" className="text-[10px] uppercase tracking-widest text-fgdim">Not green yet</h2>
        <ul aria-labelledby="not-green" className="space-y-1">
          {notGreen.map((it) => (
            <li key={it.segment_id} className="flex items-center gap-4 border-b border-line py-2">
              <span lang="zh" className="font-hanzi text-lg text-fg">{it.text}</span>
              <span className="text-sm text-fgdim">{it.lesson_title} · {it.tries} {it.tries === 1 ? 'try' : 'tries'} · best {pct(it.best?.mean)}</span>
              <Link to={`/practice/${it.lesson_id}?idx=${it.idx}`} className="ml-auto text-sm text-accent underline">Open in Practice</Link>
            </li>))}
        </ul>
      </>) : <p className="text-sm text-ok">Every sentence went green.</p>}
      <div className="flex gap-2">
        {notGreen.length > 0 && <Button label="Drill these again" variant="primary" disabled={busy} onClick={() => onAgain(notGreen.map((it) => it.segment_id))} />}
        <Button label="Done" variant={notGreen.length ? 'default' : 'primary'} onClick={onDone} />
      </div>
    </div>
  )
}
