import { afterEach, describe, it, expect, vi } from 'vitest'
import { buildExportNote, exportToAnki } from './export'
const seg = { id: 12, lesson_id: 1, idx: 0, start_s: 0, end_s: 1, text: '你好。', translation: 'Hello.', words_json: [{ word: '你好', pinyin: 'nǐhǎo', tones: [2, 3], char_from: 0, char_to: 1, syllables: [] }], ref_alignment_json: null, difficulty_flag: false, anki_note_id: null, last_score: null, best_score: null, attempts: 0 }
const cfg = { deckName: 'Shadow', modelName: 'Mining', fields: { sentence: 'Sentence', pinyin: 'Reading', translation: 'Meaning', audio: 'Audio' } }
describe('buildExportNote', () => {
  it('maps fields, pinyin and audio', () => {
    const n = buildExportNote(seg, 'QUJD', { deckName: 'Shadow', modelName: 'Mining', fields: { sentence: 'Sentence', pinyin: 'Reading', translation: 'Meaning', audio: 'Audio' } })
    expect(n.fields).toEqual({ Sentence: '你好。', Reading: 'nǐhǎo', Meaning: 'Hello.' })
    expect(n.audio![0]).toEqual({ filename: 'shadow_12.mp3', data: 'QUJD', fields: ['Audio'] })
    expect(n.tags).toEqual(['shadow']); expect(n.options!.allowDuplicate).toBe(false)
  })
  it('leaves out unmapped pinyin and translation fields', () => {
    const n = buildExportNote({ ...seg, translation: null }, 'QUJD', { deckName: 'D', modelName: 'M', fields: { sentence: 'S', translation: 'T', audio: 'A' } })
    expect(n.fields).toEqual({ S: '你好。' })
  })
})

describe('exportToAnki', () => {
  afterEach(() => { vi.restoreAllMocks() })
  const ankiReply = (result: unknown, error: string | null = null) => new Response(JSON.stringify({ result, error }))
  const addNoteBodies = (f: { mock: { calls: unknown[][] } }) => f.mock.calls.slice(1).map((c) => JSON.parse((c[1] as RequestInit).body as string))

  it('fetches the mp3, base64-encodes it and adds the note', async () => {
    const f = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('ABC'))
      .mockResolvedValueOnce(ankiReply(777))
    expect(await exportToAnki(seg, 'http://anki', cfg)).toBe(777)
    expect(String(f.mock.calls[0][0])).toMatch(/\/segments\/12\/audio\?fmt=mp3/)
    expect((f.mock.calls[0][1] as RequestInit | undefined)?.cache).toBe('no-cache') // never a stale pre-edit clip
    expect(f.mock.calls[1][0]).toBe('http://anki')
    const [body] = addNoteBodies(f)
    expect(body.action).toBe('addNote')
    expect(body.params.note.audio[0].data).toBe('QUJD') // base64 of "ABC"
  })

  it('on a duplicate, asks and retries with allowDuplicate when confirmed', async () => {
    const f = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('ABC'))
      .mockResolvedValueOnce(ankiReply(null, 'cannot create note because it is a duplicate'))
      .mockResolvedValueOnce(ankiReply(778))
    const ask = vi.spyOn(window, 'confirm').mockReturnValue(true)
    expect(await exportToAnki(seg, 'http://anki', cfg)).toBe(778)
    expect(ask).toHaveBeenCalledTimes(1)
    expect(addNoteBodies(f).map((b) => b.params.note.options.allowDuplicate)).toEqual([false, true])
  })

  it('on a duplicate the user declines, throws a readable error and adds nothing', async () => {
    const f = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('ABC'))
      .mockResolvedValueOnce(ankiReply(null, 'cannot create note because it is a duplicate'))
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    await expect(exportToAnki(seg, 'http://anki', cfg)).rejects.toThrow(/already in Anki/)
    expect(f).toHaveBeenCalledTimes(2)
  })

  it('fails readably when the clip cannot be fetched, without calling Anki', async () => {
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(new Response('nope', { status: 404, statusText: 'Not Found' }))
    await expect(exportToAnki(seg, 'http://anki', cfg)).rejects.toThrow(/clip.*404/)
    expect(f).toHaveBeenCalledTimes(1)
  })

  it('fails readably when AnkiConnect cannot be reached', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('ABC'))
      .mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await expect(exportToAnki(seg, 'http://anki', cfg)).rejects.toThrow(/Cannot reach AnkiConnect at http:\/\/anki/)
  })
})
