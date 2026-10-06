import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { LessonDetail } from '../api/types'
import Shell from '../components/Shell'
import { flaggedFirst } from '../lib/stats'
import { exportToAnki } from '../anki/export'
import { useSettings } from '../store/settings'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// Sentences worth another go: flagged as difficult, or (from Phase 2) last scored below 0.6.
export default function Review() {
  const [lessons, setLessons] = useState<LessonDetail[]>([])
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState('')
  const [sending, setSending] = useState(false)
  const { ankiUrl, exportNote } = useSettings()
  useEffect(() => {
    let cancelled = false
    api.lessons.list()
      .then((ls) => Promise.all(ls.filter((l) => l.status === 'ready').map((l) => api.lessons.get(l.id))))
      .then((d) => { if (!cancelled) setLessons(d) })
      .catch((e) => { if (!cancelled) setMsg(`Could not load lessons: ${message(e)}`) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])
  const rows = flaggedFirst(lessons)
  async function sendAll() {
    if (!exportNote) { setMsg('Configure the export note type in Settings'); return }
    setSending(true); setMsg('')
    let n = 0, failed = ''
    for (const r of rows) { try { await exportToAnki(r.segment, ankiUrl, exportNote); n++ } catch (e) { failed = message(e) } }
    setMsg(`${n} sent to Anki${failed ? ` · some failed: ${failed}` : ''}`)
    setSending(false)
  }
  return (
    <Shell><div className="max-w-4xl mx-auto p-6 space-y-3">
      <div className="flex justify-between items-center"><h1 className="text-fghi">Review · {rows.length}</h1><button className="btn" onClick={sendAll} disabled={!rows.length || sending}>A → Anki all</button></div>
      {msg && <p className="text-sm text-fgdim">{msg}</p>}
      {!loading && !rows.length && !msg && <p className="text-sm text-fgdim">Nothing to review. Flag a sentence with ⚑ while practising and it shows up here.</p>}
      {rows.map((r) => (
        <div key={r.segment.id} className="flex items-center gap-3 border-b border-line py-2 text-sm">
          <span className="text-fgdim w-32 truncate">{r.lesson.title}</span><span className="font-hanzi flex-1">{r.segment.text}</span>
          <span className="text-fgdim">{r.segment.difficulty_flag ? '⚑' : ''} {r.segment.last_score != null ? Math.round(r.segment.last_score * 100) : ''}</span>
          <Link className="btn" to={`/practice/${r.lesson.id}?seg=${r.segment.idx}`}>Practise</Link>
        </div>))}
    </div></Shell>
  )
}
