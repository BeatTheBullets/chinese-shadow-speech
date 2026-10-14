import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { DrillFocus, DrillRecent, DrillSession, DrillSummary } from '../api/types'
import Shell from '../components/Shell'
import { pct } from '../lib/score'

const EMPTY = "Practise a few sentences first — drills start once there's enough to know your weak spots."
const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
// A focus nobody has sentences for is a 404 from the queue builder; say so plainly rather than as a status line.
const startError = (e: unknown) =>
  e instanceof ApiError && e.status === 404 ? 'No sentences contain this focus yet.' : `Could not start the drill: ${e instanceof ApiError ? e.detail : message(e)}`

// Placeholder until the runner lands (Task 7): it receives the started session and walks its queue.
function DrillRunner({ session }: { session: DrillSession }) {
  return <p className="text-fghi">{session.label} · {session.items.length} sentences</p>
}

// Placeholder until the summary view lands (Task 7).
function SummaryView({ summary }: { summary: DrillSummary }) {
  return <p className="text-fghi">{summary.label} · {pct(summary.first_mean)} → {pct(summary.best_mean)}</p>
}

function FocusRow({ focus, onStart, busy }: { focus: DrillFocus; onStart: (f: DrillFocus) => void; busy: boolean }) {
  return (
    <div className="flex items-center gap-4 border-b border-line py-2">
      <span className="text-fghi">{focus.label}</span>
      <span className="text-sm text-fgdim">your mean {pct(focus.mean)} · {focus.n} syllables</span>
      <button className="btn ml-auto" disabled={busy} onClick={() => onStart(focus)}>Start</button>
    </div>
  )
}

export default function Drill() {
  const [params] = useSearchParams()
  const [list, setList] = useState<{ focuses: DrillFocus[]; auto: { kind: string; key: string } | null } | null>(null)
  const [last, setLast] = useState<DrillRecent | null>(null)
  const [session, setSession] = useState<DrillSession | null>(null)
  const [summary, setSummary] = useState<DrillSummary | null>(null)
  const [starting, setStarting] = useState(false)
  const [error, setError] = useState('')

  const start = useCallback((focus: { kind: string; key: string }) => {
    setStarting(true); setError('')
    api.drill.start({ kind: focus.kind, key: focus.key })
      .then(setSession)
      .catch((e) => setError(startError(e)))
      .finally(() => setStarting(false))
  }, [])

  useEffect(() => {
    let cancelled = false
    api.drill.focuses().then((v) => { if (!cancelled) setList(v) }).catch((e) => { if (!cancelled) setError(`Could not load drill focuses: ${message(e)}`) })
    // The last drill is a convenience link; failing to load it is not worth a message.
    api.drill.recent(1).then((v) => { if (!cancelled) setLast(v.find((s) => s.ended_at != null) ?? null) }).catch(() => {})
    return () => { cancelled = true }
  }, [])

  // "Drill this" from Stats links here with the focus in the query: start it straight away. The ref keeps StrictMode's
  // double effect from creating two sessions.
  const kind = params.get('kind'), key = params.get('key')
  const direct = useRef(false)
  useEffect(() => {
    if (!kind || !key || direct.current) return
    direct.current = true
    start({ kind, key })
  }, [kind, key, start])

  if (session) return <Shell><div className="max-w-4xl mx-auto p-6"><DrillRunner session={session} /></div></Shell>
  if (summary) return <Shell><div className="max-w-4xl mx-auto p-6"><SummaryView summary={summary} /></div></Shell>

  const auto = list?.auto ? list.focuses.find((f) => f.kind === list.auto!.kind && f.key === list.auto!.key) ?? null : null
  const alternatives = (list?.focuses ?? []).filter((f) => f !== auto).slice(0, 2)
  const seeSummary = (id: number) => api.drill.summary(id).then(setSummary).catch((e) => setError(`Could not load the summary: ${message(e)}`))
  return (
    <Shell><div className="max-w-4xl mx-auto p-6 space-y-4">
      <h1 className="text-fghi">Drill</h1>
      {error && <p className="text-sm text-bad">{error}</p>}
      {kind && key && starting ? <p className="text-sm text-fgdim">Starting…</p>
        : !list ? (!error && <p className="text-sm text-fgdim">Loading…</p>)
        : !list.focuses.length ? <p className="text-sm text-fgdim">{EMPTY} <Link to="/library" className="text-accent underline">Open the Library</Link></p>
        : (<>
          {auto && <section className="bg-panel border border-line rounded p-4"><h2 className="text-fghi">Today's focus</h2><FocusRow focus={auto} onStart={start} busy={starting} /></section>}
          {alternatives.length > 0 && <section className="bg-panel border border-line rounded p-4"><h2 className="text-fgdim">Or drill</h2>
            {alternatives.map((f) => <FocusRow key={`${f.kind}:${f.key}`} focus={f} onStart={start} busy={starting} />)}</section>}
        </>)}
      {last && <div className="flex items-center gap-4 text-sm text-fgdim">
        <span>Last drill: {last.label} · {pct(last.first_mean)} → {pct(last.best_mean)}</span>
        <button className="btn" onClick={() => void seeSummary(last.id)}>See summary</button>
      </div>}
    </div></Shell>
  )
}
