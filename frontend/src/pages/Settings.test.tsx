import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useSettings } from '../store/settings'

const h = vi.hoisted(() => ({ setup: vi.fn() }))
vi.mock('../anki/listening', async (importOriginal) => ({ ...(await importOriginal<typeof import('../anki/listening')>()), setupListeningDeck: h.setup }))
import Settings from './Settings'

const exportNote = { deckName: 'chinese-shadow-speech', modelName: 'Shadow Listening',
  fields: { sentence: 'Sentence', audio: 'Audio', pinyin: 'Pinyin', translation: 'Translation', source: 'Source', link: 'Link' } }

describe('<Settings>', () => {
  afterEach(() => { cleanup(); vi.restoreAllMocks(); h.setup.mockReset(); useSettings.setState({ exportNote: null }) })

  it('offers the bookmarklet for this origin', () => {
    render(<Settings />)
    const link = screen.getByRole('link', { name: '→ chinese-shadow-speech' })
    expect(link.getAttribute('href')).toBe(`javascript:location.href='${window.location.origin}/library?add='+encodeURIComponent(location.href)`)
  })

  it('sets up the listening deck after confirming and uses it for export', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({ result: [], error: null })))
    h.setup.mockResolvedValue({ deckCreated: true, modelCreated: true, exportNote })
    render(<Settings />)
    fireEvent.click(screen.getByRole('button', { name: 'Set up chinese-shadow-speech deck' }))
    expect(await screen.findByText(/Created deck chinese-shadow-speech, created note type Shadow Listening/)).toBeInTheDocument()
    expect(h.setup).toHaveBeenCalledWith(useSettings.getState().ankiUrl)
    expect(useSettings.getState().exportNote).toEqual(exportNote)
  })

  it('does nothing unless confirmed', () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    render(<Settings />)
    fireEvent.click(screen.getByRole('button', { name: 'Set up chinese-shadow-speech deck' }))
    expect(h.setup).not.toHaveBeenCalled()
  })

  it('shows an AnkiConnect error verbatim after a short explanation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    h.setup.mockRejectedValue(new Error('collection is not available'))
    render(<Settings />)
    fireEvent.click(screen.getByRole('button', { name: 'Set up chinese-shadow-speech deck' }))
    expect(await screen.findByText('Could not set up the deck. AnkiConnect said: collection is not available')).toBeInTheDocument()
    expect(useSettings.getState().exportNote).toBeNull()
  })

  it('explains an unreachable Anki instead of blaming AnkiConnect', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    h.setup.mockRejectedValue(new TypeError('Failed to fetch'))
    render(<Settings />)
    fireEvent.click(screen.getByRole('button', { name: 'Set up chinese-shadow-speech deck' }))
    expect(await screen.findByText(`Cannot reach AnkiConnect at ${useSettings.getState().ankiUrl}. Is Anki open with AnkiConnect, and is the URL right above?`)).toBeInTheDocument()
  })

  it('shows a note type problem without the AnkiConnect prefix', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const { NoteTypeError } = await import('../anki/listening')
    h.setup.mockRejectedValue(new NoteTypeError('The existing note type has no Sentence or Audio field.'))
    render(<Settings />)
    fireEvent.click(screen.getByRole('button', { name: 'Set up chinese-shadow-speech deck' }))
    expect(await screen.findByText('Could not set up the deck. The existing note type has no Sentence or Audio field.')).toBeInTheDocument()
  })
})
