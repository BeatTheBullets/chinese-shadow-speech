import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { api, ApiError } from '../api/client'
import type { Job, Lesson } from '../api/types'
import { addQuestion } from '../lib/handoff'
import { canRebuild, deleteConfirmText, groupBySpeaker, needsPolling, rebuildConfirmText, renamePatch } from '../lib/library'
import { useSettings } from '../store/settings'
import { runAnkiImport } from '../anki/runImport'
import Shell from '../components/Shell'
import Button from '../ui/Button'
import Card from '../ui/Card'

const BACKEND_HINT = 'Is the backend running?'
const ANKI_HINT = 'Is Anki open with AnkiConnect, and is the URL right in Settings?'
function readable(e: unknown, hint: string): string {
  if (e instanceof ApiError) return e.detail
  if (e instanceof TypeError) return `could not reach the server (${e.message}). ${hint}`
  return e instanceof Error ? e.message : String(e)
}

export default function Library() {
  const [lessons, setLessons] = useState<Lesson[]>([])
  const [jobs, setJobs] = useState<Record<number, Job>>({})
  const [note, setNote] = useState<{ text: string; lessonId?: number }>({ text: '' })
  const setMsg = useCallback((text: string) => setNote({ text }), [])   // a plain message carries no lesson link
  const [importing, setImporting] = useState(false)
  const { languageParent, importQueries, ankiUrl } = useSettings()
  const closers = useRef<(() => void)[]>([])
  const [link, setLink] = useState('')
  const adding = useRef(false)          // one paste is submitted at a time
  const [params] = useSearchParams()
  const navigate = useNavigate()
  const addHandled = useRef(false)      // StrictMode runs effects twice; the ?add= question comes once
  const reload = useCallback(() => api.lessons.list().then(setLessons).catch((e) => setMsg(`Could not load library: ${readable(e, BACKEND_HINT)}`)), [setMsg])
  useEffect(() => { reload() }, [reload])
  const polling = needsPolling(lessons)
  useEffect(() => {
    if (!polling) return
    const t = setInterval(reload, 2500)
    return () => clearInterval(t)
  }, [polling, reload])
  useEffect(() => () => closers.current.forEach((c) => c()), [])

  function watch(job_id: string, lesson_id: number, onEnd?: (j: Job) => void) {
    closers.current.push(api.jobs.events(job_id, (j) => {
      setJobs((m) => ({ ...m, [lesson_id]: j }))
      if (j.status === 'done' || j.status === 'error') { reload(); onEnd?.(j) }
    }, reload))
  }
  async function addYoutube(url: string) {
    const u = url.trim()
    if (!u) return
    if (adding.current) return
    adding.current = true
    try {
      const r = await api.lessons.youtube(u)
      setLink('')
      await reload()
      if (r.job_id) { watch(r.job_id, r.lesson_id); setMsg('Adding the video: downloading…') }
      else setNote({ text: 'That video is already in the library.', lessonId: r.lesson_id })
    } catch (e) { setMsg(`Could not add the video: ${readable(e, BACKEND_HINT)}`) }
    finally { adding.current = false }
  }
  // The bookmarklet opens /library?add=<url>: ask once, take the parameter out of the address bar, add on yes.
  useEffect(() => {
    const url = params.get('add')
    if (url == null || addHandled.current) return
    addHandled.current = true
    const title = params.get('title')
    navigate('/library', { replace: true })
    if (window.confirm(addQuestion(url, title))) void addYoutube(url)
  }, [params]) // eslint-disable-line react-hooks/exhaustive-deps -- only a new ?add= matters
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
  async function removeLesson(l: Lesson) {
    if (!window.confirm(deleteConfirmText(l))) return
    try { await api.lessons.remove(l.id); setMsg(`Deleted "${l.title}".`) }
    catch (e) { setMsg(`Could not delete "${l.title}": ${readable(e, BACKEND_HINT)}`) }
    await reload()
  }
  // A failed rebuild leaves the lesson as it was (ready), so its error is told here, not on the tile.
  async function rebuildLesson(l: Lesson) {
    if (!window.confirm(rebuildConfirmText(l))) return
    try {
      const r = await api.lessons.rebuild(l.id)
      await reload()
      watch(r.job_id, l.id, (j) => setNote(j.status === 'error'
        ? { text: `Could not rebuild the text of "${l.title}": ${j.error}` }
        : { text: `Rebuilt the text of "${l.title}".`, lessonId: l.id }))
    } catch (e) { setMsg(`Could not rebuild the text of "${l.title}": ${readable(e, BACKEND_HINT)}`) }
  }
  async function renameLesson(l: Lesson) {
    const title = window.prompt('Title', l.title)
    const body = renamePatch(l, title, title == null ? null : window.prompt('Speaker / channel name', l.speaker))
    if (!body) return
    try { await api.lessons.patch(l.id, body) }
    catch (e) { setMsg(`Could not rename "${l.title}": ${readable(e, BACKEND_HINT)}`) }
    await reload()
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
        <div className="flex flex-wrap gap-3 items-center border border-dashed border-line rounded-xl bg-panel p-4"
          onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); onFiles(e.dataTransfer.files) }}>
          <label className="flex-1 min-w-[12rem] text-fgdim text-sm cursor-pointer hover:text-fg">Drop audio/video (+ .srt) here, or click to choose
            <input type="file" multiple className="hidden" onChange={(e) => { onFiles(e.target.files); e.target.value = '' }} /></label>
          <input className="inp w-72 max-w-full" placeholder="Paste a YouTube link" aria-label="Paste a YouTube link" value={link}
            onChange={(e) => setLink(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); void addYoutube(link) } }} />
          {importQueries.map((q) => <Button key={q.name} label={`Import ${q.name} from Anki`} disabled={importing} onClick={() => void importQuery(q.name)} />)}
          {!importQueries.length && <Link to="/settings" className="btn">Set up Anki import</Link>}
        </div>
        {note.text && <p className="text-sm text-fgdim">{note.text}
          {note.lessonId != null && lessons.some((l) => l.id === note.lessonId && l.status === 'ready') && <> <Link to={`/practice/${note.lessonId}`} className="text-accent underline">Open it</Link></>}</p>}
        {groups.map((g) => (
          <section key={g.speaker}>
            <h2 className="text-xs uppercase tracking-widest text-fgdim mb-2 flex justify-between">
              <span>{g.pinned && '★ '}{g.speaker} · {g.lessons.length} lesson{g.lessons.length > 1 ? 's' : ''}</span></h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {g.lessons.map((l) => {
                const j = jobs[l.id]; const busy = l.status !== 'ready' && l.status !== 'error'
                const frac = busy ? (j?.fraction ?? 0) : (l.segment_count ? l.practised_count / l.segment_count : 0)
                const inner = (<>
                    <div lang="zh" className="font-hanzi text-lg text-fg truncate pr-16 group-hover:text-accent">{l.title}{l.source_type === 'anki' && <span className="ml-2 font-ui text-[10px] px-1.5 rounded-md bg-sound/20 text-sound">anki</span>}</div>
                    <div className="text-xs text-fgdim mt-1">
                      {l.status === 'error' ? <span className="text-bad">error: {l.error}</span>
                        : busy ? `${j?.stage ?? l.status}… ${Math.round(frac * 100)} %`
                        : `${l.segment_count} sentences · ${l.practised_count} practised${l.mean_last_score != null ? ` · mean ${Math.round(l.mean_last_score * 100)}` : ''}${l.passage_count ? ` · ${l.passages_done ?? 0} / ${l.passage_count} passages` : ''}`}
                    </div>
                    <div className="h-1 bg-line rounded-full mt-3 overflow-hidden"><div className={`h-full ${busy ? 'bg-accent' : 'bg-ok'}`} style={{ width: `${frac * 100}%` }} /></div>
                  </>)
                return (
                  <Card notched key={l.id} className="relative group">
                    {l.status === 'ready'
                      ? <Link to={`/practice/${l.id}`} className="block p-4 focus-visible:outline-offset-[-4px]">{inner}</Link>
                      : <div className="block p-4">{inner}</div>}
                    {/* outside the link, so the actions never open the lesson; every status, a broken upload included */}
                    <div className="absolute top-3 right-3 flex gap-1 opacity-50 group-hover:opacity-100 focus-within:opacity-100">
                      <button className="text-xs text-fgdim hover:text-fg px-1" title="Rename (title, speaker)" aria-label={`Rename ${l.title}`} onClick={() => renameLesson(l)}>✎</button>
                      {canRebuild(l) && <button className="text-xs text-fgdim hover:text-fg px-1" title="Rebuild text (transcribe again, keep your takes)" aria-label={`Rebuild the text of ${l.title}`} onClick={() => rebuildLesson(l)}>⟲</button>}
                      <button className="text-xs text-fgdim hover:text-bad px-1" title="Delete lesson" aria-label={`Delete ${l.title}`} onClick={() => removeLesson(l)}>✕</button>
                    </div>
                  </Card>)

              })}
            </div>
          </section>))}
      </div>
    </Shell>
  )
}
