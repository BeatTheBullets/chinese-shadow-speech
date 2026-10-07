import { api, ApiError } from '../api/client'
import type { Segment } from '../api/types'
import type { ExportNote } from '../store/settings'
import { anki, type AddNote } from './client'

// The lesson a sentence comes from, for the Source and Link fields.
export interface LessonRef { id: number; title: string; source_type: string; source_ref: string }

export const mmss = (s: number): string => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`
// "<lesson title> · mm:ss" (addendum §5.1).
export const sourceText = (lesson: LessonRef, seg: Segment): string => `${lesson.title} · ${mmss(seg.start_s)}`
// The video at the sentence's second, for YouTube lessons; '' otherwise.
export function youtubeLink(lesson: LessonRef, seg: Segment): string {
  if (lesson.source_type !== 'youtube' || !lesson.source_ref.startsWith('youtube::')) return ''
  return `https://www.youtube.com/watch?v=${lesson.source_ref.slice('youtube::'.length)}&t=${Math.floor(seg.start_s)}`
}

// One sentence as a new Anki note in the configured note type: text, pinyin (per word), translation, source and link
// (when mapped and the lesson is known) and the clip.
export function buildExportNote(seg: Segment, mp3b64: string, cfg: ExportNote, allowDuplicate = false, lesson?: LessonRef): AddNote {
  const fields: Record<string, string> = { [cfg.fields.sentence]: seg.text }
  if (cfg.fields.pinyin) fields[cfg.fields.pinyin] = (seg.words_json ?? []).map((w) => w.pinyin).join(' ')
  if (cfg.fields.translation && seg.translation) fields[cfg.fields.translation] = seg.translation
  if (lesson && cfg.fields.source) fields[cfg.fields.source] = sourceText(lesson, seg)
  const link = lesson ? youtubeLink(lesson, seg) : ''
  if (link && cfg.fields.link) fields[cfg.fields.link] = link
  return {
    deckName: cfg.deckName, modelName: cfg.modelName, fields, tags: ['shadow', `shadow::${seg.lesson_id}`],
    options: { allowDuplicate, duplicateScope: 'deck' },
    audio: [{ filename: `shadow_${seg.id}.mp3`, data: mp3b64, fields: [cfg.fields.audio] }],
  }
}

async function blobToBase64(b: Blob): Promise<string> {
  const bytes = new Uint8Array(await b.arrayBuffer()); let s = ''
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(s)
}

// addNote, with a network failure (Anki closed, wrong URL, CORS) turned into a readable message.
async function addNote(ankiUrl: string, note: AddNote): Promise<number> {
  try { return await anki(ankiUrl).addNote(note) }
  catch (e) {
    if (e instanceof TypeError) throw new Error(`Cannot reach AnkiConnect at ${ankiUrl}. Is Anki open with AnkiConnect, and is the URL right in Settings?`)
    throw e
  }
}

// Sends one sentence to Anki (the only write to Anki the app makes). A duplicate in the deck is added only when
// the user confirms it. Resolves to the new note id.
export async function exportToAnki(seg: Segment, ankiUrl: string, cfg: ExportNote, lesson?: LessonRef): Promise<number> {
  // no-cache: revalidate, so a clip re-cut by an edit in another tab or before a reload is never sent stale
  const res = await fetch(api.segments.audioUrl(seg.id, 'mp3'), { cache: 'no-cache' })
  if (!res.ok) throw new Error(`Could not get the sentence clip: ${res.status} ${res.statusText}`)
  const b64 = await blobToBase64(await res.blob())
  try { return await addNote(ankiUrl, buildExportNote(seg, b64, cfg, false, lesson)) }
  catch (e) {
    if (!/duplicate/i.test((e as Error).message)) throw e
    if (!window.confirm(`"${seg.text}" is already in the Anki deck ${cfg.deckName}. Add it anyway?`)) throw new Error(`"${seg.text}" is already in Anki, not added again.`)
    return addNote(ankiUrl, buildExportNote(seg, b64, cfg, true, lesson))
  }
}

// A sentence already has a note in Anki: it was imported from Anki, or the app sent it there before.
export const inAnki = (seg: Segment) => seg.anki_note_id != null

// The question to ask before sending a sentence that is already in Anki again; null when there is nothing to ask.
export function reexportQuestion(seg: Segment): string | null {
  return inAnki(seg) ? `"${seg.text}" is already in Anki. Send it again?` : null
}

// Bulk export leaves out sentences already in Anki.
export function splitForExport<T extends { segment: Segment }>(rows: T[]): { todo: T[]; skipped: number } {
  const todo = rows.filter((r) => !inAnki(r.segment))
  return { todo, skipped: rows.length - todo.length }
}

// Sends one sentence and records the new note on it (so Review skips it and A asks first); resolves to the
// updated sentence. A sentence imported from Anki keeps its own note id, which a re-import identifies it by.
export async function exportAndRecord(seg: Segment, ankiUrl: string, cfg: ExportNote, lesson?: LessonRef): Promise<Segment> {
  const noteId = await exportToAnki(seg, ankiUrl, cfg, lesson)
  if (inAnki(seg)) return seg
  try { return await api.segments.patch(seg.id, { anki_note_id: noteId }) }
  catch (e) {
    const why = e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)
    throw new Error(`"${seg.text}" was sent to Anki, but could not be marked as sent: ${why}`)
  }
}
