import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { Job, Lesson } from '../api/types'
import { groupBySpeaker, needsPolling } from '../lib/library'
import { useSettings } from '../store/settings'
import { runAnkiImport } from '../anki/runImport'
import Shell from '../components/Shell'

const BACKEND_HINT = 'Is the backend running?'
const ANKI_HINT = 'Is Anki open with AnkiConnect, and is the URL right in Settings?'
function readable(e: unknown, hint: string): string {
  if (e instanceof TypeError) return `could not reach the server (${e.message}). ${hint}`
  return e instanceof Error ? e.message : String(e)
}

export default function Library() {
  const [lessons, setLessons] = useState<Lesson[]>([])
  const [jobs, setJobs] = useState<Record<number, Job>>({})
  const [msg, setMsg] = useState('')
  const [importing, setImporting] = useState(false)
  const { languageParent, importQueries, ankiUrl } = useSettings()
  const closers = useRef<(() => void)[]>([])
  const reload = useCallback(() => api.lessons.list().then(setLessons).catch((e) => setMsg(`Could not load library: ${readable(e, BACKEND_HINT)}`)), [])
  useEffect(() => { reload() }, [reload])
  const polling = needsPolling(lessons)
  useEffect(() => {
    if (!polling) return
    const t = setInterval(reload, 2500)
    return () => clearInterval(t)
  }, [polling, reload])
  useEffect(() => () => closers.current.forEach((c) => c()), [])

  function watch(job_id: string, lesson_id: number) {
    closers.current.push(api.jobs.events(job_id, (j) => { setJobs((m) => ({ ...m, [lesson_id]: j })); if (j.status === 'done' || j.status === 'error') reload() }, reload))
  }
  async function onFiles(files: FileList | null) {
    if (!files?.length) return
    const list = [...files]
    const media = list.find((f) => !/\.(srt|vtt|txt)$/i.test(f.name))
    const subs = list.find((f) => /\.(srt|vtt|txt)$/i.test(f.name))
    if (!media) { setMsg('Drop an audio or video file (optionally with an .srt).'); return }
    const speaker = window.prompt('Speaker / channel name?', '') ?? ''
    try {
      const r = await api.lessons.upload(media, { subtitles: subs, speaker })
      await reload(); watch(r.job_id, r.lesson_id)
    } catch (e) { setMsg(`Upload failed: ${readable(e, BACKEND_HINT)}`) }
  }
  async function importQuery(name: string) {
    const q = importQueries.find((x) => x.name === name)
    if (!q || importing) return
    setImporting(true)
    try {
      const { jobs: js, skipped } = await runAnkiImport(q, ankiUrl, setMsg)
      const why = '(no [sound:] tag, empty text or missing audio)'
      setMsg(js.length ? `${js.length} lesson(s) updating, ${skipped} note(s) skipped ${why}` : `Nothing to import: ${skipped} note(s) skipped ${why}`)
      await reload(); js.forEach((j) => watch(j.job_id, j.lesson_id))
    } catch (e) { setMsg(`Anki import failed: ${readable(e, ANKI_HINT)}`) }
    finally { setImporting(false) }
  }

  const groups = groupBySpeaker(lessons, languageParent)
  return (
    <Shell>
      <div className="max-w-6xl mx-auto p-6 space-y-6">
        <div className="flex gap-3 items-center border border-dashed border-line rounded p-4"
          onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); onFiles(e.dataTransfer.files) }}>
          <label className="flex-1 text-fgdim text-sm cursor-pointer">Drop audio/video (+ .srt) here, or click to choose
            <input type="file" multiple className="hidden" onChange={(e) => { onFiles(e.target.files); e.target.value = '' }} /></label>
          {importQueries.map((q) => <button key={q.name} className="btn" disabled={importing} onClick={() => importQuery(q.name)}>⟳ Anki · {q.name}</button>)}
          {!importQueries.length && <Link to="/settings" className="btn">Set up Anki import</Link>}
        </div>
        {msg && <p className="text-sm text-fgdim">{msg}</p>}
        {groups.map((g) => (
          <section key={g.speaker}>
            <h2 className="text-xs uppercase tracking-widest text-fgdim mb-2 flex justify-between">
              <span>{g.pinned && '★ '}{g.speaker} · {g.lessons.length} lesson{g.lessons.length > 1 ? 's' : ''}</span></h2>
            <div className="grid grid-cols-3 gap-3">
              {g.lessons.map((l) => {
                const j = jobs[l.id]; const busy = l.status !== 'ready' && l.status !== 'error'
                const frac = busy ? (j?.fraction ?? 0) : (l.segment_count ? l.practised_count / l.segment_count : 0)
                const inner = (<>
                    <div className="font-hanzi text-fghi truncate">{l.title}{l.source_type === 'anki' && <span className="ml-2 text-[10px] px-1 rounded bg-[#2b1f3a] text-[#d6c3f0]">anki</span>}</div>
                    <div className="text-xs text-fgdim mt-1">
                      {l.status === 'error' ? <span className="text-bad">error: {l.error}</span>
                        : busy ? `${j?.stage ?? l.status}… ${Math.round(frac * 100)} %`
                        : `${l.segment_count} sentences · ${l.practised_count} practised${l.mean_last_score != null ? ` · mean ${Math.round(l.mean_last_score * 100)}` : ''}`}
                    </div>
                    <div className="h-1 bg-panel2 rounded mt-2 overflow-hidden"><div className={`h-full ${busy ? 'bg-accent' : 'bg-ok'}`} style={{ width: `${frac * 100}%` }} /></div>
                  </>)
                return l.status === 'ready'
                  ? <Link key={l.id} to={`/practice/${l.id}`} className="bg-panel border border-line rounded p-3 block hover:border-accent">{inner}</Link>
                  : <div key={l.id} className="bg-panel border border-line rounded p-3 block">{inner}</div>

              })}
            </div>
          </section>))}
      </div>
    </Shell>
  )
}
