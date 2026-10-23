import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ApiError, api } from '../api/client'
import type { DrillFocus, DrillRecent, DrillSession, DrillSummary } from '../api/types'
import DrillRunner from '../components/DrillRunner'
import DrillSummaryView from '../components/DrillSummary'
import Shell from '../components/Shell'
import { pct } from '../lib/score'
import Button from '../ui/Button'

const EMPTY = "Practise a few sentences first — drills start once there's enough to know your weak spots."
const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
// A focus nobody has sentences for is a 404 from the queue builder; say so plainly rather than as a status line.
const startError = (e: unknown) =>
  e instanceof ApiError && e.status === 404 ? 'No sentences contain this focus yet.' : `Could not start the drill: ${e instanceof ApiError ? e.detail : message(e)}`

// `main`: today's focus, the start screen's one obvious action (spec §1.3), so its Start is the accent button.
function FocusRow({ focus, onStart, busy, main = false }: { focus: DrillFocus; onStart: (f: DrillFocus) => void; busy: boolean; main?: boolean }) {
  return (
    <div className="flex items-center gap-4 border-b border-line py-2 last:border-b-0">
      <span className="text-fg font-semibold">{focus.label}</span>
      <span className="text-sm text-fgdim">your mean {pct(focus.mean)} · {focus.n} syllables</span>
      <span className="ml-auto"><Button label="Start" variant={main ? 'primary' : 'default'} size={main ? 'lg' : 'md'} disabled={busy} onClick={() => onStart(focus)} /></span>
    </div>
  )
}

export default function Drill() {
  const [params, setParams] = useSearchParams()
  const [list, setList] = useState<{ focuses: DrillFocus[]; auto: { kind: string; key: string } | null } | null>(null)
  const [last, setLast] = useState<DrillRecent | null>(null)
  const [session, setSession] = useState<DrillSession | null>(null)
  const [summary, setSummary] = useState<DrillSummary | null>(null)
  const [starting, setStarting] = useState(false)
  const [ending, setEnding] = useState(false)
  const [error, setError] = useState('')

  // segment_ids: "Drill these again" from a summary, a new run on exactly those sentences.
  const start = useCallback((focus: { kind: string; key: string; segment_ids?: number[] }) => {
    setStarting(true); setError('')
    const { kind, key, segment_ids } = focus
    api.drill.start(segment_ids ? { kind, key, segment_ids } : { kind, key })
      .then((s) => { setSummary(null); setSession(s) })
      .catch((e) => setError(startError(e)))
      .finally(() => setStarting(false))
  }, [])

  // Loaded on arrival and again back from a summary (the drill just done moved the means and is now the last drill).
  const alive = useRef(true)
  const load = useCallback(() => {
    api.drill.focuses().then((v) => { if (alive.current) setList(v) }).catch((e) => { if (alive.current) setError(`Could not load drill focuses: ${message(e)}`) })
    // The last drill is a convenience link; failing to load it is not worth a message.
    api.drill.recent(1).then((v) => { if (alive.current) setLast(v.find((s) => s.ended_at != null) ?? null) }).catch(() => {})
  }, [])
  useEffect(() => {
    alive.current = true
    load()
    return () => { alive.current = false }
  }, [load])

  // "Drill this" from Stats links here with the focus in the query: start it straight away. The ref keeps StrictMode's
  // double effect from creating two sessions.
  const kind = params.get('kind'), key = params.get('key')
  const direct = useRef(false)
  useEffect(() => {
    if (!kind || !key || direct.current) return
    direct.current = true
    start({ kind, key })
  }, [kind, key, start])

  const seeSummary = (id: number) => api.drill.summary(id).then((s) => { if (alive.current) setSummary(s) })
    .catch((e) => { if (alive.current) setError(`Could not load the summary: ${message(e)}`) })
  // The runner has ended the session (after the last sentence or Finish): its summary replaces it.
  function finished(id: number) {
    setSession(null); setEnding(true)
    void seeSummary(id).finally(() => { if (alive.current) setEnding(false) })
  }
  // Back to the start screen. A "Drill this" query is dropped so nothing starts again from it.
  function backToStart() {
    setSummary(null); setError('')
    if (params.has('kind') || params.has('key')) setParams({}, { replace: true })
    load()
  }

  if (session) return <Shell><div className="max-w-4xl mx-auto px-6 py-4"><DrillRunner key={session.id} session={session} onFinish={() => finished(session.id)} /></div></Shell>
  if (ending) return <Shell><div className="max-w-4xl mx-auto p-6"><p className="text-sm text-fgdim">Loading the summary…</p></div></Shell>
  if (summary) return (
    <Shell><div className="max-w-4xl mx-auto p-6 space-y-2">
      {error && <p className="text-sm text-bad">{error}</p>}
      <DrillSummaryView summary={summary} onAgain={(ids) => start({ kind: summary.kind, key: summary.key, segment_ids: ids })} onDone={backToStart} busy={starting} />
    </div></Shell>
  )

  const auto = list?.auto ? list.focuses.find((f) => f.kind === list.auto!.kind && f.key === list.auto!.key) ?? null : null
  const alternatives = (list?.focuses ?? []).filter((f) => f !== auto).slice(0, 2)
  return (
    <Shell><div className="max-w-4xl mx-auto p-6 space-y-4">
      <h1 className="text-xl text-fg font-semibold">Drill</h1>
      {error && <p className="text-sm text-bad">{error}</p>}
      {kind && key && starting ? <p className="text-sm text-fgdim">Starting…</p>
        : !list ? (!error && <p className="text-sm text-fgdim">Loading…</p>)
        : !list.focuses.length ? <p className="text-sm text-fgdim">{EMPTY} <Link to="/library" className="text-accent underline">Open the Library</Link></p>
        : (<>
          {auto && <section className="bg-panel border border-line rounded-xl p-4"><h2 className="text-[10px] uppercase tracking-widest text-accent">Today's focus</h2><FocusRow focus={auto} onStart={start} busy={starting} main /></section>}
          {alternatives.length > 0 && <section className="bg-panel border border-line rounded-xl p-4"><h2 className="text-[10px] uppercase tracking-widest text-fgdim">Or drill</h2>
            {alternatives.map((f) => <FocusRow key={`${f.kind}:${f.key}`} focus={f} onStart={start} busy={starting} />)}</section>}
        </>)}
      {last && <div className="flex items-center gap-4 text-sm text-fgdim">
        <span>Last drill: {last.label} · {pct(last.first_mean)} → {pct(last.best_mean)}</span>
        <Button label="See summary" variant="ghost" onClick={() => void seeSummary(last.id)} />
      </div>}
    </div></Shell>
  )
}
