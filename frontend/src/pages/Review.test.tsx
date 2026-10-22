import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LessonDetail, Segment } from '../api/types'
import { useSettings } from '../store/settings'

const h = vi.hoisted(() => ({
  api: { lessons: { list: vi.fn(), get: vi.fn() }, review: { unexported: vi.fn() } },
  exportAndRecord: vi.fn(),
}))
vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api/client')>()), api: h.api }))
vi.mock('../anki/export', async (importOriginal) => ({ ...(await importOriginal<typeof import('../anki/export')>()), exportAndRecord: h.exportAndRecord }))
import Review from './Review'

const seg = (id: number, text: string, anki_note_id: number | null): Segment => ({
  id, lesson_id: 1, idx: id, start_s: 0, end_s: 1, text, translation: null, words_json: null, ref_alignment_json: null,
  difficulty_flag: true, anki_note_id, last_score: null, best_score: null, attempts: 0,
})
const lesson: LessonDetail = {
  id: 1, title: 'L', speaker: '', source_type: 'upload', source_ref: '', duration_s: 4, created_at: '', status: 'ready', error: null,
  segment_count: 2, practised_count: 0, mean_last_score: null, segments: [seg(1, '你好', null), seg(2, '再见', 99)],
}

function deferred<T>() {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((res) => { resolve = res })
  return { promise, resolve }
}

describe('<Review> bulk export', () => {
  beforeEach(() => { h.exportAndRecord.mockReset(); h.api.review.unexported.mockResolvedValue([]) })
  afterEach(() => { cleanup(); useSettings.setState({ exportNote: null }) })

  it('skips sentences already in Anki and marks the ones it sends, so a second run sends nothing', async () => {
    useSettings.setState({ exportNote: { deckName: 'D', modelName: 'M', fields: { sentence: 'S', audio: 'A' } } })
    h.api.lessons.list.mockResolvedValue([lesson]); h.api.lessons.get.mockResolvedValue(lesson)
    h.exportAndRecord.mockImplementation(async (s: Segment) => ({ ...s, anki_note_id: 500 }))
    render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Review /></MemoryRouter>)
    await screen.findByText('你好')
    fireEvent.click(screen.getByRole('button', { name: 'Send all to Anki' }))
    expect(await screen.findByText('1 sent to Anki · 1 skipped (already in Anki)')).toBeInTheDocument()
    expect(h.exportAndRecord.mock.calls.map((c) => (c[0] as Segment).id)).toEqual([1])
    fireEvent.click(screen.getByRole('button', { name: 'Send all to Anki' }))
    expect(await screen.findByText('0 sent to Anki · 2 skipped (already in Anki)')).toBeInTheDocument()
    expect(h.exportAndRecord).toHaveBeenCalledTimes(1)
  })

  it('lists practised sentences not in Anki and sends them with the same bulk send', async () => {
    useSettings.setState({ exportNote: { deckName: 'chinese-shadow-speech', modelName: 'Shadow Listening', fields: { sentence: 'Sentence', audio: 'Audio' } } })
    h.api.lessons.list.mockResolvedValue([])
    h.api.review.unexported.mockResolvedValue([{ lesson_id: 3, lesson_title: 'YT', lesson_source_type: 'youtube', lesson_source_ref: 'youtube::abcDEF12345',
      last_attempt_at: '2026-10-07T09:05:00', segment: { ...seg(5, '我今天想学中文', null), difficulty_flag: false } }])
    h.exportAndRecord.mockImplementation(async (s: Segment) => ({ ...s, anki_note_id: 9 }))
    render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Review /></MemoryRouter>)
    expect(await screen.findByText('Practised, not in Anki · 1')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Send 1 to Anki' }))
    expect(await screen.findByText('sent ✓')).toBeInTheDocument()
    expect(h.exportAndRecord.mock.calls[0][3]).toEqual({ id: 3, title: 'YT', source_type: 'youtube', source_ref: 'youtube::abcDEF12345' })
  })

  describe('a sentence in both lists', () => {
    const cfg = { deckName: 'chinese-shadow-speech', modelName: 'Shadow Listening', fields: { sentence: 'Sentence', audio: 'Audio' } }
    const both = seg(1, '我今天想学中文', null)
    const flagged: LessonDetail = { ...lesson, segments: [both] }
    const unexported = [{ lesson_id: 1, lesson_title: 'L', lesson_source_type: 'upload', lesson_source_ref: '', last_attempt_at: '2026-10-07T09:05:00', segment: both }]
    beforeEach(() => {
      useSettings.setState({ exportNote: cfg })
      h.api.lessons.list.mockResolvedValue([flagged]); h.api.lessons.get.mockResolvedValue(flagged)
      h.api.review.unexported.mockResolvedValue(unexported)
    })
    const show = async () => {
      render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Review /></MemoryRouter>)
      await screen.findByText('Practised, not in Anki · 1')
      await screen.findByRole('button', { name: 'Send all to Anki' })
    }

    it('the list cannot send while the bulk send runs, and afterwards shows it sent', async () => {
      const d = deferred<Segment>()
      h.exportAndRecord.mockReturnValue(d.promise)
      await show()
      fireEvent.click(screen.getByRole('button', { name: 'Send all to Anki' }))
      expect(screen.getByRole('button', { name: 'Send 1 to Anki' })).toBeDisabled()
      await act(async () => { d.resolve({ ...both, anki_note_id: 9 }) })
      expect(await screen.findByText('1 sent to Anki')).toBeInTheDocument()
      expect(screen.getByText('sent ✓')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Send 0 to Anki' })).toBeDisabled()
      expect(h.exportAndRecord).toHaveBeenCalledTimes(1)
    })

    it('the bulk send waits while the list is sending, and then skips what the list sent', async () => {
      const d = deferred<Segment>()
      h.exportAndRecord.mockReturnValue(d.promise)
      await show()
      fireEvent.click(screen.getByRole('button', { name: 'Send 1 to Anki' }))
      expect(await screen.findByText('sending…')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Send all to Anki' })).toBeDisabled()
      await act(async () => { d.resolve({ ...both, anki_note_id: 9 }) })
      expect(await screen.findByText('sent ✓')).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Send all to Anki' }))
      expect(await screen.findByText('0 sent to Anki · 1 skipped (already in Anki)')).toBeInTheDocument()
      expect(h.exportAndRecord).toHaveBeenCalledTimes(1)
    })
  })
})
