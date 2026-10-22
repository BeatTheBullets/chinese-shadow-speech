import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { LessonDetail, Segment, UnexportedItem } from '../api/types'
import ExportList, { type ExportItem } from '../components/ExportList'
import Shell from '../components/Shell'
import { flaggedFirst } from '../lib/stats'
import { exportAndRecord, splitForExport } from '../anki/export'
import { useSettings } from '../store/settings'
import Button from '../ui/Button'
import { IconAnki } from '../ui/icons'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
const toItem = (u: UnexportedItem): ExportItem => ({
  segment: u.segment, lesson: { id: u.lesson_id, title: u.lesson_title, source_type: u.lesson_source_type, source_ref: u.lesson_source_ref },
})

// Sentences worth another go (flagged, or from Phase 2 last scored below 0.6), and every practised sentence that is not
// in Anki yet (addendum §5.2: nothing is lost when Anki was closed at the end of a session).
export default function Review() {
  const [lessons, setLessons] = useState<LessonDetail[]>([])
  const [unsent, setUnsent] = useState<UnexportedItem[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState('')
  const [sending, setSending] = useState(false)
  const [listBusy, setListBusy] = useState(false) // the "Practised, not in Anki" list is sending
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
  useEffect(() => {
    let cancelled = false
    api.review.unexported()
      .then((u) => { if (!cancelled) setUnsent(u) })
      .catch((e) => { if (!cancelled) setMsg(`Could not load the practised sentences: ${message(e)}`) })
    return () => { cancelled = true }
  }, [])
  const rows = flaggedFirst(lessons)
  // Each sent sentence is marked in both lists, so neither sends it again. Only one of them sends at a time.
  const mark = (seg: Segment) => {
    setLessons((ls) => ls.map((l) => (l.id !== seg.lesson_id ? l : { ...l, segments: l.segments.map((x) => (x.id === seg.id ? seg : x)) })))
    setUnsent((u) => u && u.map((x) => (x.segment.id === seg.id ? { ...x, segment: seg } : x)))
  }
  async function sendAll() {
    if (sending || listBusy) return
    if (!exportNote) { setMsg('Configure the export note type in Settings'); return }
    setSending(true); setMsg('')
    const { todo, skipped } = splitForExport(rows)
    let n = 0; const failures: string[] = []
    for (const r of todo) { try { mark(await exportAndRecord(r.segment, ankiUrl, exportNote, r.lesson)); n++ } catch (e) { failures.push(message(e)) } }
    setMsg(`${n} sent to Anki${skipped ? ` · ${skipped} skipped (already in Anki)` : ''}${failures.length ? ` · ${failures.length} failed: ${[...new Set(failures)].join('; ')}` : ''}`)
    setSending(false)
  }
  return (
    <Shell><div className="max-w-4xl mx-auto p-6 space-y-3">
      <div className="flex justify-between items-center"><h1 className="text-xl text-fg font-semibold">Review · {rows.length}</h1>
        <Button icon={<IconAnki />} label="Send all to Anki" onClick={() => void sendAll()} disabled={!rows.length || sending || listBusy} /></div>
      {msg && <p className="text-sm text-fgdim">{msg}</p>}
      {!loading && !rows.length && !msg && <p className="text-sm text-fgdim">Nothing to review. Flag a sentence with ⚑ while practising and it shows up here.</p>}
      {rows.map((r) => (
        <div key={r.segment.id} className="flex items-center gap-3 border-b border-line py-2 text-sm">
          <span className="text-fgdim w-32 truncate">{r.lesson.title}</span><span lang="zh" className="font-hanzi text-base text-fg flex-1">{r.segment.text}</span>
          <span className="text-fgdim tabular-nums"><span className="text-warn">{r.segment.difficulty_flag ? '⚑' : ''}</span> {r.segment.last_score != null ? Math.round(r.segment.last_score * 100) : ''}</span>
          <Link className="btn hover:border-accent" to={`/practice/${r.lesson.id}?seg=${r.segment.idx}`}>Practise</Link>
        </div>))}
      <section className="space-y-2 pt-6">
        <h2 className="text-fg font-semibold">Practised, not in Anki{unsent ? ` · ${unsent.length}` : ''}</h2>
        {unsent && (unsent.length
          ? <ExportList items={unsent.map(toItem)} onSent={mark} onBusy={setListBusy} disabled={sending} />
          : <p className="text-sm text-fgdim">Every sentence you practised is in Anki.</p>)}
      </section>
    </div></Shell>
  )
}
