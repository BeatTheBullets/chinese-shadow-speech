import { StrictMode } from 'react'
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Job, Lesson } from '../api/types'

const h = vi.hoisted(() => ({
  api: { lessons: { list: vi.fn(), remove: vi.fn(), patch: vi.fn(), youtube: vi.fn(), rebuild: vi.fn() }, jobs: { events: vi.fn() }, app: { update: vi.fn().mockResolvedValue({ current: '1.0.0', latest: null, url: null, newer: false }) } },
}))
vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api/client')>()), api: h.api }))
import Library from './Library'

const lesson = (id: number, over: Partial<Lesson> = {}): Lesson => ({
  id, title: `t${id}`, speaker: 'S', source_type: 'upload', source_ref: '', duration_s: 0, created_at: `2026-01-0${id}`,
  status: 'ready', error: null, segment_count: 2, practised_count: 0, mean_last_score: null, ...over,
})

describe('Library tile actions', () => {
  beforeEach(() => {
    h.api.app.update.mockResolvedValue({ current: '1.0.0', latest: null, url: null, newer: false })
    h.api.lessons.list.mockReset(); h.api.lessons.remove.mockReset().mockResolvedValue(undefined); h.api.lessons.patch.mockReset().mockResolvedValue({})
  })
  afterEach(() => { cleanup(); vi.restoreAllMocks() })
  const show = async (ls: Lesson[]) => {
    h.api.lessons.list.mockResolvedValue(ls)
    render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Library /></MemoryRouter>)
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

  it('a tile shows passage progress', async () => {
    await show([lesson(1, { passage_count: 2, passages_done: 1 })])
    expect(screen.getByText(/1 \/ 2 passages/)).toBeInTheDocument()
  })

  it('rebuilds the text after confirmation, shows the job and says when it failed', async () => {
    h.api.lessons.rebuild.mockReset().mockResolvedValue({ job_id: 'j9', lesson_id: 1 })
    let send: (j: Job) => void = () => {}
    h.api.jobs.events.mockReset().mockImplementation((_id: string, on: (j: Job) => void) => { send = on; return () => {} })
    await show([lesson(1)])
    const ask = vi.spyOn(window, 'confirm').mockReturnValue(true)
    h.api.lessons.list.mockResolvedValue([lesson(1, { status: 'processing' })])
    fireEvent.click(screen.getByLabelText('Rebuild the text of t1'))
    await waitFor(() => expect(h.api.lessons.rebuild).toHaveBeenCalledWith(1))
    expect(ask.mock.calls[0][0]).toMatch(/keeps your takes/)
    await waitFor(() => expect(h.api.jobs.events).toHaveBeenCalledWith('j9', expect.any(Function), expect.any(Function)))
    act(() => send({ id: 'j9', stage: 'rescore', fraction: 0.5, status: 'running', error: null, lesson_id: 1 }))
    expect(await screen.findByText(/rescore… 50 %/)).toBeInTheDocument()
    h.api.lessons.list.mockResolvedValue([lesson(1)])
    act(() => send({ id: 'j9', stage: 'error', fraction: 0.5, status: 'error', error: 'no speech found', lesson_id: 1 }))
    expect(await screen.findByText('Could not rebuild the text of "t1": no speech found')).toBeInTheDocument()
  })

  it('a declined rebuild sends nothing, and an Anki lesson offers none', async () => {
    h.api.lessons.rebuild.mockReset()
    await show([lesson(1), lesson(2, { source_type: 'anki' })])
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    fireEvent.click(screen.getByLabelText('Rebuild the text of t1'))
    expect(h.api.lessons.rebuild).not.toHaveBeenCalled()
    expect(screen.queryByLabelText('Rebuild the text of t2')).toBeNull()
  })

  it('a cancelled rename sends nothing', async () => {
    await show([lesson(1)])
    vi.spyOn(window, 'prompt').mockReturnValueOnce(null)
    fireEvent.click(screen.getByLabelText('Rename t1'))
    expect(h.api.lessons.patch).not.toHaveBeenCalled()
  })
})

describe('Library YouTube hand-off', () => {
  beforeEach(() => {
    h.api.app.update.mockResolvedValue({ current: '1.0.0', latest: null, url: null, newer: false })
    h.api.lessons.list.mockReset().mockResolvedValue([lesson(1)])
    h.api.lessons.youtube.mockReset().mockResolvedValue({ job_id: 'j1', lesson_id: 2 })
    h.api.jobs.events.mockReset().mockReturnValue(() => {})
  })
  afterEach(() => { cleanup(); vi.restoreAllMocks() })
  function Where() { const l = useLocation(); return <div data-testid="where">{l.pathname + l.search}</div> }
  // StrictMode runs effects twice: the ?add= question must still come once.
  const open = (entry: string) => render(
    <StrictMode><MemoryRouter initialEntries={[entry]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <Routes><Route path="/library" element={<><Library /><Where /></>} /></Routes>
    </MemoryRouter></StrictMode>)
  const paste = async (url: string) => {
    await screen.findByText('t1')   // the first load has settled
    const box = await screen.findByLabelText('Paste a YouTube link')
    fireEvent.change(box, { target: { value: url } })
    await act(async () => { fireEvent.keyDown(box, { key: 'Enter' }) })   // let the submit settle inside act
  }

  it('a pasted link is added on Enter and its job is watched', async () => {
    open('/library')
    await paste(' https://youtu.be/abcDEF12345 ')
    await waitFor(() => expect(h.api.lessons.youtube).toHaveBeenCalledWith('https://youtu.be/abcDEF12345'))
    await waitFor(() => expect(h.api.jobs.events).toHaveBeenCalledWith('j1', expect.any(Function), expect.any(Function)))
    await screen.findByText('Adding the video: downloading…')
  })

  it('a video already in the library says so and starts no job', async () => {
    h.api.lessons.youtube.mockResolvedValue({ job_id: null, lesson_id: 1 })
    open('/library')
    await paste('https://youtu.be/abcDEF12345')
    expect(await screen.findByText('That video is already in the library.')).toBeInTheDocument()
    expect(h.api.jobs.events).not.toHaveBeenCalled()
    expect(await screen.findByText('Open it')).toBeInTheDocument()
  })

  it('the Open it link goes with its message only', async () => {
    h.api.lessons.youtube.mockResolvedValue({ job_id: null, lesson_id: 1 })
    h.api.lessons.remove.mockResolvedValue(undefined)
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    open('/library')
    await paste('https://youtu.be/abcDEF12345')
    await screen.findByText('Open it')
    fireEvent.click(screen.getByLabelText('Delete t1'))
    await screen.findByText('Deleted "t1".')
    expect(screen.queryByText('Open it')).toBeNull()
  })

  it('ignores a second Enter while a paste is being submitted', async () => {
    open('/library')
    await screen.findByText('t1')
    const box = await screen.findByLabelText('Paste a YouTube link')
    fireEvent.change(box, { target: { value: 'https://youtu.be/abcDEF12345' } })
    await act(async () => { fireEvent.keyDown(box, { key: 'Enter' }); fireEvent.keyDown(box, { key: 'Enter' }) })
    await screen.findByText('Adding the video: downloading…')
    expect(h.api.lessons.youtube).toHaveBeenCalledTimes(1)
  })

  it('?add= asks once, adds on yes and clears the parameter', async () => {
    const ask = vi.spyOn(window, 'confirm').mockReturnValue(true)
    const url = 'https://www.youtube.com/watch?v=abcDEF12345&t=3'
    open('/library?add=' + encodeURIComponent(url))
    await waitFor(() => expect(h.api.lessons.youtube).toHaveBeenCalledWith(url))
    expect(h.api.lessons.youtube).toHaveBeenCalledTimes(1)
    expect(ask).toHaveBeenCalledTimes(1)
    expect(ask).toHaveBeenCalledWith(`Add ${url} to chinese-shadow-speech?`)
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/library$/))
    await screen.findByText('Adding the video: downloading…')
  })

  it('declining ?add= adds nothing but still clears the parameter', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    open('/library?add=https%3A%2F%2Fyoutu.be%2FabcDEF12345')
    await waitFor(() => expect(screen.getByTestId('where')).toHaveTextContent(/^\/library$/))
    expect(h.api.lessons.youtube).not.toHaveBeenCalled()
  })
})
