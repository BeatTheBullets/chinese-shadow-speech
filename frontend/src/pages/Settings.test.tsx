import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useSettings } from '../store/settings'

const h = vi.hoisted(() => ({ setup: vi.fn(), voice: { get: vi.fn(), reset: vi.fn() }, cookies: { get: vi.fn(), put: vi.fn(), remove: vi.fn() } }))
vi.mock('../anki/listening', async (importOriginal) => ({ ...(await importOriginal<typeof import('../anki/listening')>()), setupListeningDeck: h.setup }))
vi.mock('../api/client', async (importOriginal) => { const m = await importOriginal<typeof import('../api/client')>(); return { ...m, api: { ...m.api, voiceProfile: h.voice, settings: { youtubeCookies: h.cookies } } } })
import Settings from './Settings'

const exportNote = { deckName: 'chinese-shadow-speech', modelName: 'Shadow Listening',
  fields: { sentence: 'Sentence', audio: 'Audio', pinyin: 'Pinyin', translation: 'Translation', source: 'Source', link: 'Link' } }

describe('<Settings>', () => {
  beforeEach(() => {
    h.voice.get.mockResolvedValue({ baseline_hz: null, spread_st: null, voiced_s: 0, updated_at: null })
    h.cookies.get.mockResolvedValue({ present: false })
  })
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

  it('shows the voice profile and resets it after confirming', async () => {
    h.voice.get.mockResolvedValue({ baseline_hz: 118.2, spread_st: 9.46, voiced_s: 252, updated_at: '2026-10-09T10:00:00Z' })
    h.voice.reset.mockResolvedValue(undefined)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<Settings />)
    expect(await screen.findByText('Your baseline: 118 Hz · range 9.5 st · from 4.2 min of speech')).toBeInTheDocument()
    h.voice.get.mockResolvedValue({ baseline_hz: null, spread_st: null, voiced_s: 0, updated_at: null })
    fireEvent.click(screen.getByRole('button', { name: 'Reset voice profile' }))
    expect(await screen.findByText(/No voice profile yet/)).toBeInTheDocument()
    expect(h.voice.reset).toHaveBeenCalled()
  })

  it('says so when the voice profile cannot be reset (the backend is down)', async () => {
    const { ApiError } = await import('../api/client')
    h.voice.reset.mockRejectedValue(new ApiError(500, 'Internal Server Error', '{"detail":"database is locked"}', 'database is locked'))
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    render(<Settings />)
    fireEvent.click(screen.getByRole('button', { name: 'Reset voice profile' }))
    expect(await screen.findByText('Could not reset the voice profile: database is locked')).toBeInTheDocument()
    h.voice.reset.mockRejectedValue(new TypeError('Failed to fetch'))
    fireEvent.click(screen.getByRole('button', { name: 'Reset voice profile' }))
    expect(await screen.findByText('Could not reset the voice profile: Failed to fetch')).toBeInTheDocument()
  })

  it('shows whether YouTube cookies were added, adds a file with the picker and removes it', async () => {
    const { ApiError } = await import('../api/client')
    h.cookies.put.mockResolvedValue({ present: true }); h.cookies.remove.mockResolvedValue(undefined)
    render(<Settings />)
    expect(await screen.findByText('Cookies: none')).toBeInTheDocument()
    expect(screen.queryByText(/config\.toml/)).toBeNull()
    expect(screen.getByText(/Some videos need you to be signed in to YouTube/)).toBeInTheDocument()
    const file = new File(['# Netscape HTTP Cookie File\n'], 'cookies.txt', { type: 'text/plain' })
    fireEvent.change(screen.getByLabelText('Cookies file'), { target: { files: [file] } })
    expect(await screen.findByText('Cookies: added')).toBeInTheDocument()
    expect(h.cookies.put).toHaveBeenCalledWith(file)
    fireEvent.click(screen.getByRole('button', { name: 'Remove cookies' }))
    expect(await screen.findByText('Cookies: none')).toBeInTheDocument()
    expect(h.cookies.remove).toHaveBeenCalled()
    h.cookies.put.mockRejectedValue(new ApiError(400, 'Bad Request', '', 'That is not a cookies.txt file'))
    fireEvent.change(screen.getByLabelText('Cookies file'), { target: { files: [file] } })
    expect(await screen.findByText('Could not add the cookies: That is not a cookies.txt file')).toBeInTheDocument()
  })

  it('shows Cookies: added when the backend already has them', async () => {
    h.cookies.get.mockResolvedValue({ present: true })
    render(<Settings />)
    expect(await screen.findByText('Cookies: added')).toBeInTheDocument()
  })
})
