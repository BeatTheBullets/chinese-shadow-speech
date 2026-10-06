import type { AnkiNotePayload } from '../api/types'
import type { NoteInfo } from './client'

export interface FieldMapping { sentence: string; audio: string; translation?: string; source?: string; url?: string }

export function parseSoundTag(v: string): string | null {
  const m = /\[sound:([^\]]+)\]/.exec(v ?? '')
  return m ? m[1] : null
}

export function stripHtml(s: string): string {
  const withBreaks = (s ?? '').replace(/<br\s*\/?>/gi, ' ').replace(/<[^>]+>/g, '')
  const el = document.createElement('textarea')
  el.innerHTML = withBreaks
  return el.value.replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim()
}

const field = (n: NoteInfo, name?: string) => (name && n.fields[name] ? n.fields[name].value : '')

export async function notesToImportPayload(
  notes: NoteInfo[], mapping: FieldMapping, fetchMedia: (filename: string) => Promise<string | false>,
): Promise<{ payload: AnkiNotePayload[]; skipped: number }> {
  const payload: AnkiNotePayload[] = []
  let skipped = 0
  for (const n of notes) {
    const filename = parseSoundTag(field(n, mapping.audio))
    const text = stripHtml(field(n, mapping.sentence).replace(/\[sound:[^\]]*\]/g, ''))
    const audio_b64 = filename ? await fetchMedia(filename) : false
    if (!filename || !text || audio_b64 === false) { skipped++; continue }
    payload.push({
      note_id: n.noteId, text, translation: stripHtml(field(n, mapping.translation)) || null,
      source: stripHtml(field(n, mapping.source)) || null, url: field(n, mapping.url) || null, audio_b64, filename,
    })
  }
  return { payload, skipped }
}
