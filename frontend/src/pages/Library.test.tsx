import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Lesson } from '../api/types'

const h = vi.hoisted(() => ({
  api: { lessons: { list: vi.fn(), remove: vi.fn(), patch: vi.fn() }, jobs: { events: vi.fn() } },
}))
vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api/client')>()), api: h.api }))
import Library from './Library'

const lesson = (id: number, over: Partial<Lesson> = {}): Lesson => ({
  id, title: `t${id}`, speaker: 'S', source_type: 'upload', source_ref: '', duration_s: 0, created_at: `2026-01-0${id}`,
  status: 'ready', error: null, segment_count: 2, practised_count: 0, mean_last_score: null, ...over,
})

describe('Library tile actions', () => {
  beforeEach(() => {
    h.api.lessons.list.mockReset(); h.api.lessons.remove.mockReset().mockResolvedValue(undefined); h.api.lessons.patch.mockReset().mockResolvedValue({})
  })
  afterEach(() => { cleanup(); vi.restoreAllMocks() })
  const show = async (ls: Lesson[]) => {
    h.api.lessons.list.mockResolvedValue(ls)
    render(<MemoryRouter><Library /></MemoryRouter>)
    await screen.findByText(ls[0].title)
  }

  it('deletes a failed lesson after confirmation and reloads', async () => {
    await show([lesson(1, { status: 'error', error: 'interrupted — the server restarted during processing; delete and re-upload' })])
    const ask = vi.spyOn(window, 'confirm').mockReturnValue(true)
    h.api.lessons.list.mockResolvedValue([])
    fireEvent.click(screen.getByLabelText('Delete t1'))
    await waitFor(() => expect(h.api.lessons.remove).toHaveBeenCalledWith(1))
    expect(ask.mock.calls[0][0]).toMatch(/Delete "t1"/)
    await waitFor(() => expect(screen.queryByText('t1')).toBeNull())
  })

  it('does nothing when the delete is not confirmed, and also offers it on a processing lesson', async () => {
    await show([lesson(1, { status: 'processing' })])
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    fireEvent.click(screen.getByLabelText('Delete t1'))
    expect(h.api.lessons.remove).not.toHaveBeenCalled()
  })

  it('renames title and speaker without opening the lesson', async () => {
    await show([lesson(1)])
    vi.spyOn(window, 'prompt').mockReturnValueOnce('新标题').mockReturnValueOnce('李子柒')
    fireEvent.click(screen.getByLabelText('Rename t1'))
    await waitFor(() => expect(h.api.lessons.patch).toHaveBeenCalledWith(1, { title: '新标题', speaker: '李子柒' }))
    await waitFor(() => expect(h.api.lessons.list).toHaveBeenCalledTimes(2))
  })

  it('a cancelled rename sends nothing', async () => {
    await show([lesson(1)])
    vi.spyOn(window, 'prompt').mockReturnValueOnce(null)
    fireEvent.click(screen.getByLabelText('Rename t1'))
    expect(h.api.lessons.patch).not.toHaveBeenCalled()
  })
})
