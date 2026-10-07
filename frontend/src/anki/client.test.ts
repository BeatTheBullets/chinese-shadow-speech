import { describe, it, expect, vi } from 'vitest'
import { ankiRequest, anki } from './client'

describe('ankiRequest', () => {
  it('posts action/version/params and unwraps result', async () => {
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ result: ['Default'], error: null })))
    const r = await ankiRequest<string[]>('http://127.0.0.1:8765', 'deckNames')
    expect(r).toEqual(['Default'])
    expect(JSON.parse(f.mock.calls[0][1]!.body as string)).toEqual({ action: 'deckNames', version: 6, params: {} })
  })
  it('throws on error field', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ result: null, error: 'bad' })))
    await expect(anki('http://x').findNotes('deck:X')).rejects.toThrow('bad')
  })
  it('creates a deck', async () => {
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ result: 1, error: null })))
    await anki('http://x').createDeck('chinese-shadow-speech')
    expect(JSON.parse(f.mock.calls[0][1]!.body as string)).toEqual({ action: 'createDeck', version: 6, params: { deck: 'chinese-shadow-speech' } })
  })
})
