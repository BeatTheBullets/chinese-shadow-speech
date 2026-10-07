import { afterEach, describe, it, expect, vi } from 'vitest'
import { stripHtml } from './import'
import { buildExportNote, youtubeLink, exportAndRecord, exportToAnki, reexportQuestion, splitForExport } from './export'
const seg = { id: 12, lesson_id: 1, idx: 0, start_s: 0, end_s: 1, text: '你好。', translation: 'Hello.', words_json: [{ word: '你好', pinyin: 'nǐhǎo', tones: [2, 3], char_from: 0, char_to: 1, syllables: [] }], ref_alignment_json: null, difficulty_flag: false, anki_note_id: null, last_score: null, best_score: null, attempts: 0 }
const cfg = { deckName: 'Shadow', modelName: 'Mining', fields: { sentence: 'Sentence', pinyin: 'Reading', translation: 'Meaning', audio: 'Audio' } }
describe('buildExportNote', () => {
  it('maps fields, pinyin and audio', () => {
    const n = buildExportNote(seg, 'QUJD', { deckName: 'Shadow', modelName: 'Mining', fields: { sentence: 'Sentence', pinyin: 'Reading', translation: 'Meaning', audio: 'Audio' } })
    expect(n.fields).toEqual({ Sentence: '你好。', Reading: 'nǐhǎo', Meaning: 'Hello.' })
    expect(n.audio![0]).toEqual({ filename: 'shadow_12.mp3', data: 'QUJD', fields: ['Audio'] })
    expect(n.tags).toEqual(['shadow', 'shadow::1']); expect(n.options!.allowDuplicate).toBe(false)
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

describe('exportAndRecord', () => {
  afterEach(() => { vi.restoreAllMocks() })
  const ankiReply = (result: unknown) => new Response(JSON.stringify({ result, error: null }))

  it('sends the sentence, then records the new note id on it and resolves to the updated sentence', async () => {
    const f = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('ABC'))
      .mockResolvedValueOnce(ankiReply(777))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...seg, anki_note_id: 777 })))
    const out = await exportAndRecord(seg, 'http://anki', cfg)
    expect(out.anki_note_id).toBe(777)
    expect(String(f.mock.calls[2][0])).toMatch(/\/segments\/12$/)
    expect(f.mock.calls[2][1]).toMatchObject({ method: 'PATCH', body: JSON.stringify({ anki_note_id: 777 }) })
  })

  it('keeps the note id of a sentence imported from Anki (a re-import identifies its notes by it)', async () => {
    const f = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('ABC'))
      .mockResolvedValueOnce(ankiReply(778))
    const imported = { ...seg, anki_note_id: 5 }
    expect(await exportAndRecord(imported, 'http://anki', cfg)).toBe(imported)
    expect(f).toHaveBeenCalledTimes(2)
  })

  it('says so when the note was added but could not be recorded', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('ABC'))
      .mockResolvedValueOnce(ankiReply(779))
      .mockResolvedValueOnce(new Response('{"detail":"boom"}', { status: 500, statusText: 'Internal Server Error' }))
    await expect(exportAndRecord(seg, 'http://anki', cfg)).rejects.toThrow(/sent to Anki, but could not be marked/)
  })
})

describe('reexportQuestion', () => {
  it('asks only for a sentence already in Anki', () => {
    expect(reexportQuestion(seg)).toBeNull()
    expect(reexportQuestion({ ...seg, anki_note_id: 5 })).toMatch(/"你好。" is already in Anki/)
  })
})

describe('splitForExport', () => {
  it('skips sentences already in Anki, imported from it or sent before', () => {
    const rows = [{ segment: seg }, { segment: { ...seg, id: 13, anki_note_id: 5 } }, { segment: { ...seg, id: 14 } }]
    const { todo, skipped } = splitForExport(rows)
    expect(todo.map((r) => r.segment.id)).toEqual([12, 14])
    expect(skipped).toBe(1)
  })
})

describe('listening card fields', () => {
  afterEach(() => { vi.restoreAllMocks() })
  const full = { deckName: 'chinese-shadow-speech', modelName: 'Shadow Listening', fields: { sentence: 'Sentence', pinyin: 'Pinyin', translation: 'Translation', audio: 'Audio', source: 'Source', link: 'Link' } }
  const yt = { id: 7, title: '学中文', source_type: 'youtube', source_ref: 'youtube::abcDEF12345' }

  it('adds Source (title · mm:ss), the YouTube Link at that second, and the lesson tag', () => {
    const n = buildExportNote({ ...seg, lesson_id: 7, start_s: 83.6 }, 'QUJD', full, false, yt)
    expect(n.fields).toMatchObject({ Sentence: '你好。', Source: '学中文 · 01:23', Link: 'https://www.youtube.com/watch?v=abcDEF12345&amp;t=83' })
    expect(n.tags).toEqual(['shadow', 'shadow::7'])
  })
  it('leaves Link out for lessons not from YouTube', () => {
    const n = buildExportNote(seg, 'QUJD', full, false, { id: 1, title: 'L', source_type: 'upload', source_ref: 'a.mp4' })
    expect(n.fields.Source).toBe('L · 00:00')
    expect(n.fields).not.toHaveProperty('Link')
  })
  it('exportAndRecord passes the lesson on to the note', async () => {
    const f = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response('ABC'))
      .mockResolvedValueOnce(new Response(JSON.stringify({ result: 780, error: null })))
      .mockResolvedValueOnce(new Response(JSON.stringify({ ...seg, anki_note_id: 780 })))
    await exportAndRecord(seg, 'http://anki', full, { id: 1, title: 'L', source_type: 'upload', source_ref: 'a.mp4' })
    expect(JSON.parse((f.mock.calls[1][1] as RequestInit).body as string).params.note.fields.Source).toBe('L · 00:00')
  })
  it('escapes HTML in the fields, and import reads them back unchanged', () => {
    const lesson = { id: 2, title: 'Vlog <3 & "学中文"', source_type: 'upload', source_ref: 'a.mp4' }
    const n = buildExportNote({ ...seg, text: '一<二 & 三', translation: 'a < b & c' }, 'QUJD', full, false, lesson)
    expect(n.fields.Sentence).toBe('一&lt;二 &amp; 三')
    expect(n.fields.Translation).toBe('a &lt; b &amp; c')
    expect(n.fields.Source).toBe('Vlog &lt;3 &amp; &quot;学中文&quot; · 00:00')
    expect(stripHtml(n.fields.Sentence)).toBe('一<二 & 三')
    expect(stripHtml(n.fields.Source)).toBe('Vlog <3 & "学中文" · 00:00')
  })
  it('escapes & in the Link', () => {
    expect(buildExportNote(seg, 'QUJD', full, false, yt).fields.Link).toBe('https://www.youtube.com/watch?v=abcDEF12345&amp;t=0')
  })
  it('youtubeLink is empty for a youtube lesson whose source_ref is not youtube::<id>', () => {
    expect(youtubeLink({ ...yt, source_ref: 'https://youtu.be/x' }, seg)).toBe('')
  })
})
