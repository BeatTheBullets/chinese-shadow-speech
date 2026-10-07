import { afterEach, describe, expect, it, vi } from 'vitest'
import { LISTENING_DECK, LISTENING_MODEL, listeningModel, setupListeningDeck } from './listening'

const reply = (result: unknown, error: string | null = null) => new Response(JSON.stringify({ result, error }))
const bodies = (f: { mock: { calls: unknown[][] } }) => f.mock.calls.map((c) => JSON.parse((c[1] as RequestInit).body as string))

describe('setupListeningDeck', () => {
  afterEach(() => { vi.restoreAllMocks() })

  it('creates the deck and the note type when missing and maps every field', async () => {
    const f = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(reply(['Default'])).mockResolvedValueOnce(reply(1))
      .mockResolvedValueOnce(reply(['Basic'])).mockResolvedValueOnce(reply({}))
    const r = await setupListeningDeck('http://anki')
    const sent = bodies(f)
    expect(sent.map((b) => b.action)).toEqual(['deckNames', 'createDeck', 'modelNames', 'createModel'])
    expect(sent[1].params).toEqual({ deck: 'shadow-speech' })
    const model = sent[3].params
    expect(model).toEqual(listeningModel)
    expect(model.modelName).toBe('Shadow Listening')
    expect(model.inOrderFields).toEqual(['Audio', 'Sentence', 'Pinyin', 'Translation', 'Source', 'Link'])
    expect(model.cardTemplates[0].Front).toContain('{{Audio}}')
    expect(model.cardTemplates[0].Front).toContain('What did you hear?')
    expect(model.cardTemplates[0].Back).toMatch(/\{\{FrontSide\}\}[\s\S]*<hr[\s\S]*\{\{Sentence\}\}[\s\S]*\{\{Pinyin\}\}[\s\S]*\{\{Translation\}\}[\s\S]*<a href="\{\{Link\}\}">\{\{Source\}\}<\/a>/)
    expect(r).toEqual({ deckCreated: true, modelCreated: true, exportNote: { deckName: LISTENING_DECK, modelName: LISTENING_MODEL,
      fields: { sentence: 'Sentence', audio: 'Audio', pinyin: 'Pinyin', translation: 'Translation', source: 'Source', link: 'Link' } } })
  })

  it('reuses an existing deck and note type without changing them', async () => {
    const f = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(reply(['shadow-speech'])).mockResolvedValueOnce(reply(['Shadow Listening']))
      .mockResolvedValueOnce(reply(['Audio', 'Sentence', 'Source']))
    const r = await setupListeningDeck('http://anki')
    expect(bodies(f).map((b) => b.action)).toEqual(['deckNames', 'modelNames', 'modelFieldNames'])
    expect([r.deckCreated, r.modelCreated]).toEqual([false, false])
    expect(r.exportNote.fields).toEqual({ sentence: 'Sentence', audio: 'Audio', source: 'Source' })
  })

  it('refuses an existing note type without Sentence and Audio fields', async () => {
    vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(reply(['shadow-speech'])).mockResolvedValueOnce(reply(['Shadow Listening']))
      .mockResolvedValueOnce(reply(['Front', 'Back']))
    await expect(setupListeningDeck('http://anki')).rejects.toThrow(/no Sentence or Audio field/)
  })

  it('passes AnkiConnect errors through', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(reply(['Default'])).mockResolvedValueOnce(reply(null, 'deck name is invalid'))
    await expect(setupListeningDeck('http://anki')).rejects.toThrow('deck name is invalid')
  })
})
