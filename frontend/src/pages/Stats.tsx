import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { ActivityStats, SentenceStats, SyllableStats, ToneStats } from '../api/types'
import Shell from '../components/Shell'
import ToneMatrix from '../components/ToneMatrix'
import ToneTrend from '../components/ToneTrend'
import { TONE_NAMES, pct } from '../lib/score'
import { activityBars } from '../lib/stats'

const EMPTY = 'No scores yet — record a take to see tone stats.'
const plural = (n: number) => `${n} attempt${n === 1 ? '' : 's'}`
const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// One series (minutes per day), so one hue: the theme's reference blue, thin bars with a rounded data end, recessive
// axis. Attempts are printed under each bar rather than encoded as a second scale. Hover a bar for its exact values.
function ActivityChart({ days }: { days: ActivityStats['days'] }) {
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
        <line x1="0" x2={W} y1={top + plotH} y2={top + plotH} stroke="#2a3139" />
        <line x1="0" x2={W} y1={top} y2={top} stroke="#2a3139" strokeDasharray="2 4" />
        <text x="0" y={top - 1} fontSize="9" fill="#7c8793">{max} min</text>
        {bars.map((b, i) => {
          const x = i * slot + (slot - bw) / 2, bh = b.minutes ? Math.max(2, (b.minutes / max) * plotH) : 0
          return (
            <g key={days[i].date} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)}>
              <rect x={i * slot} y={0} width={slot} height={H} fill="transparent" />
              {bh > 0 && <path d={`M${x},${top + plotH} V${top + Math.min(4, bh) + plotH - bh} q0,-${Math.min(4, bh)} ${Math.min(4, bh)},-${Math.min(4, bh)} H${x + bw - Math.min(4, bh)} q${Math.min(4, bh)},0 ${Math.min(4, bh)},${Math.min(4, bh)} V${top + plotH} Z`} fill={hover === i ? '#b5cde6' : '#8fb3d9'} />}
              <text x={x + bw / 2} y={top + plotH + 12} fontSize="9" textAnchor="middle" fill="#7c8793">{b.label}</text>
              <text x={x + bw / 2} y={top + plotH + 26} fontSize="9" textAnchor="middle" fill="#cfd6dd">{b.attempts || ''}</text>
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

const Panel = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <section className="bg-panel border border-line rounded p-4 space-y-2"><h2 className="text-fghi">{title}</h2>{children}</section>)
const Empty = () => <p className="text-sm text-fgdim">{EMPTY}</p>

export default function Stats() {
  const [activity, setActivity] = useState<ActivityStats | null>(null)
  const [sentences, setSentences] = useState<SentenceStats | null>(null)
  const [syllables, setSyllables] = useState<SyllableStats | null>(null)
  const [tones, setTones] = useState<ToneStats | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let cancelled = false
    const run = <T,>(p: Promise<T>, set: (v: T) => void) => p.then((v) => { if (!cancelled) set(v) }).catch((e) => { if (!cancelled) setError(`Could not load stats: ${message(e)}`) })
    void run(api.stats.activity(30), setActivity); void run(api.stats.sentences(), setSentences)
    void run(api.stats.syllables(), setSyllables); void run(api.stats.tones(), setTones)
    return () => { cancelled = true }
  }, [])
  const row = 'border-b border-line py-1 flex gap-4'
  return (
    <Shell><div className="max-w-4xl mx-auto p-6 space-y-4">
      <h1 className="text-fghi">Stats</h1>
      {error && <p className="text-sm text-bad">{error}</p>}
      <Panel title="Activity · last 30 days">{activity ? <ActivityChart days={activity.days} /> : <p className="text-sm text-fgdim">Loading…</p>}</Panel>
      <Panel title="Sentences">
        {sentences && (sentences.regressed.length || sentences.by_last.length) ? (<>
          {sentences.regressed.length > 0 && <div><h3 className="text-sm text-fgdim">Regressed</h3>{sentences.regressed.map((s) => <div key={s.segment_id} className={row}><span>#{s.segment_id}</span><span>last {Math.round(s.last * 100)}</span><span>best {Math.round(s.best * 100)}</span><span className="text-fgdim">{plural(s.attempts)}</span></div>)}</div>}
          {sentences.by_last.length > 0 && <div><h3 className="text-sm text-fgdim">By last score</h3>{sentences.by_last.map((s) => <div key={s.segment_id} className={row}><span>#{s.segment_id}</span><span>last {Math.round(s.last * 100)}</span><span>best {Math.round(s.best * 100)}</span><span className="text-fgdim">{plural(s.attempts)}</span></div>)}</div>}
        </>) : <Empty />}
      </Panel>
      <Panel title="Characters">
        {syllables?.syllables.length ? syllables.syllables.map((s) => (
          <div key={`${s.ch}${s.pinyin}${s.tone}`} className={row}>
            <span className="font-hanzi text-fghi">{s.ch}</span> <span>{s.pinyin}{s.tone}</span> <span>mean {pct(s.mean)}</span> <span className="text-fgdim">n {s.n}</span>
            {s.trend != null && <span className={s.trend >= 0 ? 'text-ok' : 'text-bad'}>{s.trend >= 0 ? '↑' : '↓'} {Math.abs(Math.round(s.trend * 100))}</span>}
          </div>)) : <Empty />}
      </Panel>
      <Panel title="Tones">
        {tones && (tones.tones.length || tones.pairs.length) ? (<>
          <ToneTrend weeks={tones.weeks} />
          {tones.tones.map((t) => <div key={t.tone} className={row}><span>Tone {t.tone} ({TONE_NAMES[t.tone]})</span><span>mean {pct(t.mean)}</span><span className="text-fgdim">n {t.n}</span></div>)}
          <h3 className="text-sm text-fgdim">After tone × tone</h3>
          <ToneMatrix pairs={tones.pairs} />
        </>) : <Empty />}
      </Panel>
    </div></Shell>
  )
}
