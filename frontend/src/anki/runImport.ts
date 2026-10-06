import { anki, type NoteInfo } from './client'
import { notesToImportPayload } from './import'
import { api } from '../api/client'
import type { ImportQuery } from '../store/settings'

export async function runAnkiImport(q: ImportQuery, ankiUrl: string, onProgress: (msg: string) => void) {
  const a = anki(ankiUrl)
  const ids = await a.findNotes(q.query)
  onProgress(`${ids.length} notes match`)
  const notes: NoteInfo[] = []
  for (let i = 0; i < ids.length; i += 50) notes.push(...(await a.notesInfo(ids.slice(i, i + 50))))
  let done = 0
  const { payload, skipped } = await notesToImportPayload(notes, q.mapping, async (name) => {
    const r = await a.retrieveMediaFile(name); done++
    if (done % 10 === 0) onProgress(`fetched ${done}/${notes.length} clips`)
    return r
  })
  if (!payload.length) return { jobs: [], skipped }
  const res = await api.lessons.ankiImport(q.name, payload)
  return { jobs: res.jobs, skipped }
}
