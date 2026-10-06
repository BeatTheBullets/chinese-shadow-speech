import { describe, it, expect } from 'vitest'
import { parseSoundTag, stripHtml, notesToImportPayload } from './import'

const mapping = { sentence: 'Sentence', audio: 'Audio', translation: 'Meaning', source: 'Source' }
const note = (id: number, fields: Record<string, string>) => ({
  noteId: id, modelName: 'Mining', tags: [], fields: Object.fromEntries(Object.entries(fields).map(([k, v], i) => [k, { value: v, order: i }])),
})

describe('import helpers', () => {
  it('parses first sound tag', () => {
    expect(parseSoundTag('[sound:a.mp3][sound:b.mp3]')).toBe('a.mp3')
    expect(parseSoundTag('nothing')).toBeNull()
  })
  it('strips html', () => {
    expect(stripHtml('<div>你好<br>世界</div>&nbsp;')).toBe('你好 世界')
  })
  it('builds payload and skips notes without audio', async () => {
    const notes = [
      note(1, { Sentence: '<b>你好。</b>', Audio: '[sound:a.mp3]', Meaning: 'Hi', Source: 'v1.mp4 00:00:01.000' }),
      note(2, { Sentence: '再见。', Audio: '', Meaning: '', Source: '' }),
    ]
    const { payload, skipped } = await notesToImportPayload(notes, mapping, async (n) => (n === 'a.mp3' ? 'QUJD' : false))
    expect(skipped).toBe(1)
    expect(payload).toEqual([{ note_id: 1, text: '你好。', translation: 'Hi', source: 'v1.mp4 00:00:01.000', url: null, audio_b64: 'QUJD', filename: 'a.mp3' }])
  })
  it('imports only the first clip when the audio field has two sound tags', async () => {
    const fetched: string[] = []
    const notes = [note(3, { Sentence: '你好。', Audio: '[sound:a.mp3][sound:b.mp3]', Meaning: '', Source: '' })]
    const { payload, skipped } = await notesToImportPayload(notes, mapping, async (n) => { fetched.push(n); return 'QUJD' })
    expect(skipped).toBe(0)
    expect(payload).toHaveLength(1)
    expect(payload[0].filename).toBe('a.mp3')
    expect(fetched).toEqual(['a.mp3'])
  })
})
