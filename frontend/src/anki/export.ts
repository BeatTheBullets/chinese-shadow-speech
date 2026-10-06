import { api } from '../api/client'
import type { Segment } from '../api/types'
import type { ExportNote } from '../store/settings'
import { anki, type AddNote } from './client'

// One sentence as a new Anki note in the configured note type: text, pinyin (per word), translation and the clip.
export function buildExportNote(seg: Segment, mp3b64: string, cfg: ExportNote, allowDuplicate = false): AddNote {
  const fields: Record<string, string> = { [cfg.fields.sentence]: seg.text }
  if (cfg.fields.pinyin) fields[cfg.fields.pinyin] = (seg.words_json ?? []).map((w) => w.pinyin).join(' ')
  if (cfg.fields.translation && seg.translation) fields[cfg.fields.translation] = seg.translation
  return {
    deckName: cfg.deckName, modelName: cfg.modelName, fields, tags: ['shadow'],
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
export async function exportToAnki(seg: Segment, ankiUrl: string, cfg: ExportNote): Promise<number> {
  // no-cache: revalidate, so a clip re-cut by an edit in another tab or before a reload is never sent stale
  const res = await fetch(api.segments.audioUrl(seg.id, 'mp3'), { cache: 'no-cache' })
  if (!res.ok) throw new Error(`Could not get the sentence clip: ${res.status} ${res.statusText}`)
  const b64 = await blobToBase64(await res.blob())
  try { return await addNote(ankiUrl, buildExportNote(seg, b64, cfg)) }
  catch (e) {
    if (!/duplicate/i.test((e as Error).message)) throw e
    if (!window.confirm(`"${seg.text}" is already in the Anki deck ${cfg.deckName}. Add it anyway?`)) throw new Error(`"${seg.text}" is already in Anki, not added again.`)
    return addNote(ankiUrl, buildExportNote(seg, b64, cfg, true))
  }
}
