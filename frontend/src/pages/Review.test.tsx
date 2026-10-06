import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { LessonDetail, Segment } from '../api/types'
import { useSettings } from '../store/settings'

const h = vi.hoisted(() => ({
  api: { lessons: { list: vi.fn(), get: vi.fn() } },
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

describe('<Review> bulk export', () => {
  afterEach(() => { cleanup(); useSettings.setState({ exportNote: null }) })

  it('skips sentences already in Anki and marks the ones it sends, so a second run sends nothing', async () => {
    useSettings.setState({ exportNote: { deckName: 'D', modelName: 'M', fields: { sentence: 'S', audio: 'A' } } })
    h.api.lessons.list.mockResolvedValue([lesson]); h.api.lessons.get.mockResolvedValue(lesson)
    h.exportAndRecord.mockImplementation(async (s: Segment) => ({ ...s, anki_note_id: 500 }))
    render(<MemoryRouter><Review /></MemoryRouter>)
    await screen.findByText('你好')
    fireEvent.click(screen.getByRole('button', { name: 'A → Anki all' }))
    expect(await screen.findByText('1 sent to Anki · 1 skipped (already in Anki)')).toBeInTheDocument()
    expect(h.exportAndRecord.mock.calls.map((c) => (c[0] as Segment).id)).toEqual([1])
    fireEvent.click(screen.getByRole('button', { name: 'A → Anki all' }))
    expect(await screen.findByText('0 sent to Anki · 2 skipped (already in Anki)')).toBeInTheDocument()
    expect(h.exportAndRecord).toHaveBeenCalledTimes(1)
  })
})
