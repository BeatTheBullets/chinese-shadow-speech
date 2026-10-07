import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Segment } from '../api/types'
import { useSettings } from '../store/settings'

const h = vi.hoisted(() => ({ exportAndRecord: vi.fn() }))
vi.mock('../anki/export', async (importOriginal) => ({ ...(await importOriginal<typeof import('../anki/export')>()), exportAndRecord: h.exportAndRecord }))
import ExportList from './ExportList'

const seg = (id: number, text: string): Segment => ({
  id, lesson_id: 1, idx: id, start_s: 0, end_s: 1, text, translation: null, words_json: null, ref_alignment_json: null,
  difficulty_flag: false, anki_note_id: null, last_score: null, best_score: null, attempts: 1,
})
const lesson = { id: 1, title: 'L', source_type: 'youtube', source_ref: 'youtube::abcDEF12345' }
const items = [{ segment: seg(1, '我今天想学中文。'), lesson }, { segment: seg(2, '嗯嗯，对对。'), lesson }, { segment: seg(3, '好的。'), lesson }]
const cfg = { deckName: 'chinese-shadow-speech', modelName: 'Shadow Listening', fields: { sentence: 'Sentence', audio: 'Audio' } }
const show = (onSent = vi.fn()) => render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><ExportList items={items} onSent={onSent} /></MemoryRouter>)

describe('<ExportList>', () => {
  beforeEach(() => { h.exportAndRecord.mockReset(); useSettings.setState({ exportNote: cfg }) })
  afterEach(() => { cleanup(); useSettings.setState({ exportNote: null }) })

  it('ticks every sentence except fillers', () => {
    show()
    expect(screen.getByRole('checkbox', { name: /我今天想学中文/ })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /嗯嗯，对对/ })).not.toBeChecked()
    expect(screen.getByRole('checkbox', { name: /好的/ })).not.toBeChecked()
    expect(screen.getByRole('button', { name: 'Send 1 to Anki' })).toBeEnabled()
  })

  it('sends the ticked rows with their lesson and shows a result per row', async () => {
    const onSent = vi.fn()
    h.exportAndRecord.mockImplementation(async (s: Segment) => ({ ...s, anki_note_id: 9 }))
    show(onSent)
    fireEvent.click(screen.getByRole('checkbox', { name: /好的/ }))
    fireEvent.click(screen.getByRole('button', { name: 'Send 2 to Anki' }))
    await waitFor(() => expect(onSent).toHaveBeenCalledTimes(2))
    expect(h.exportAndRecord.mock.calls.map((c) => [(c[0] as Segment).id, c[3]])).toEqual([[1, lesson], [3, lesson]])
    expect(screen.getAllByText('sent ✓')).toHaveLength(2)
    expect(screen.getByRole('button', { name: 'Send 0 to Anki' })).toBeDisabled()
  })

  it('with Anki unreachable each row shows its error, nothing is marked sent, and the row stays ticked', async () => {
    const onSent = vi.fn()
    h.exportAndRecord.mockRejectedValue(new Error('Cannot reach AnkiConnect at http://127.0.0.1:8765.'))
    show(onSent)
    fireEvent.click(screen.getByRole('button', { name: 'Send 1 to Anki' }))
    expect(await screen.findByText(/Cannot reach AnkiConnect/)).toBeInTheDocument()
    expect(onSent).not.toHaveBeenCalled()
    expect(screen.getByRole('checkbox', { name: /我今天想学中文/ })).toBeChecked()
    expect(screen.getByRole('button', { name: 'Send 1 to Anki' })).toBeEnabled()
  })

  it('without an export note type it points to Settings', () => {
    useSettings.setState({ exportNote: null })
    show()
    expect(screen.getByText(/Set up the Anki export in Settings first/)).toBeInTheDocument()
  })
})
