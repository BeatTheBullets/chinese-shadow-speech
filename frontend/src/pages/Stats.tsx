import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api/client'
import type { ActivityStats, DrillRecent, SentenceStats, SoundStats, ToneStats } from '../api/types'
import ActivityChart from '../components/ActivityChart'
import Shell from '../components/Shell'
import SoundsPanel from '../components/SoundsPanel'
import ToneMatrix from '../components/ToneMatrix'
import ToneTrend from '../components/ToneTrend'
import { TONE_NAMES, pct } from '../lib/score'
import Card from '../ui/Card'

const EMPTY = 'No scores yet — record a take to see tone stats.'
const plural = (n: number) => `${n} attempt${n === 1 ? '' : 's'}`
const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// Stats panels are main cards: notched window-frame corners (spec §1.2). Content is today's; the redesign is a later plan.
const Panel = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <Card notched className="p-5"><section className="space-y-2"><h2 className="text-fg font-semibold">{title}</h2>{children}</section></Card>)
const Empty = () => <p className="text-sm text-fgdim">{EMPTY}</p>

export default function Stats() {
  const [activity, setActivity] = useState<ActivityStats | null>(null)
  const [sentences, setSentences] = useState<SentenceStats | null>(null)
  const [tones, setTones] = useState<ToneStats | null>(null)
  const [sounds, setSounds] = useState<SoundStats | null>(null)
  const [drills, setDrills] = useState<DrillRecent[] | null>(null)
  const [error, setError] = useState('')
  const navigate = useNavigate()
  const drill = (kind: string, key: string) => navigate(`/drill?kind=${kind}&key=${encodeURIComponent(key)}`)
  useEffect(() => {
    let cancelled = false
    const run = <T,>(p: Promise<T>, set: (v: T) => void) => p.then((v) => { if (!cancelled) set(v) }).catch((e) => { if (!cancelled) setError(`Could not load stats: ${message(e)}`) })
    void run(api.stats.activity(30), setActivity); void run(api.stats.sentences(), setSentences)
    void run(api.stats.tones(), setTones); void run(api.stats.sounds(), setSounds); void run(api.drill.recent(10), setDrills)
    return () => { cancelled = true }
  }, [])
  const small = 'text-xs text-accent ml-auto hover:underline'
  const row = 'border-b border-line py-1 flex gap-4'
  return (
    <Shell><div className="max-w-4xl mx-auto p-6 space-y-4">
      <h1 className="text-xl text-fg font-semibold">Stats</h1>
      {error && <p className="text-sm text-bad">{error}</p>}
      <Panel title="Activity · last 30 days">{activity ? <ActivityChart days={activity.days} /> : <p className="text-sm text-fgdim">Loading…</p>}</Panel>
      <Panel title="Sentences">
        {sentences?.sentences.length ? sentences.sentences.map((s) => (
          <div key={s.segment_id} className={row}><span>{s.text}</span><span>last {Math.round(s.last * 100)}</span><span>best {Math.round(s.best * 100)}</span><span className="text-fgdim">{plural(s.attempts)}</span></div>
        )) : <Empty />}
      </Panel>
      <Panel title="Drills">
        {drills?.length ? drills.map((d) => (
          <div key={d.id} className={row}>
            <span data-drill-label>{d.label}</span><span className="text-fgdim">{d.started_at.slice(0, 10)}</span>
            {d.first_mean != null && d.best_mean != null && <span>{pct(d.first_mean)} → {pct(d.best_mean)}</span>}
          </div>)) : drills ? <p className="text-sm text-fgdim">No drills yet.</p> : <p className="text-sm text-fgdim">Loading…</p>}
      </Panel>
      <Panel title="Tones">
        {tones && (tones.tones.length || tones.pairs.length) ? (<>
          <ToneTrend weeks={tones.weeks} />
          {tones.tones.map((t) => <div key={t.tone} className={row}><span>Tone {t.tone} ({TONE_NAMES[t.tone]})</span><span>mean {pct(t.mean)}</span><span className="text-fgdim">n {t.n}</span>
            {t.tone >= 1 && t.tone <= 4 && <button type="button" className={small} aria-label={`Drill tone ${t.tone}`} onClick={() => drill('tone', String(t.tone))}>Drill this</button>}</div>)}
          <h3 className="text-sm text-fgdim">After tone × tone</h3>
          <ToneMatrix pairs={tones.pairs} onDrill={(k) => drill('pair', k)} />
        </>) : <Empty />}
      </Panel>
      <Panel title="Sounds">{sounds ? <SoundsPanel stats={sounds} onDrill={(k) => drill('sound', k)} /> : <p className="text-sm text-fgdim">Loading…</p>}</Panel>
    </div></Shell>
  )
}
