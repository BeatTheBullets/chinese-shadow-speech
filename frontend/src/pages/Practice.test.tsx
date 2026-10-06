import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { LessonDetail, Segment } from '../api/types'
import { usePractice } from '../store/practice'

const h = vi.hoisted(() => ({
  api: {
    lessons: { get: vi.fn() },
    sessions: { create: vi.fn(), end: vi.fn() },
    segments: { audioUrl: (id: number, fmt = 'opus') => `/seg/${id}.${fmt}`, postAttempt: vi.fn(), patch: vi.fn() },
  },
  rec: { start: vi.fn(), stop: vi.fn(), sampleRate: 44100 },
  toWav16k: vi.fn(() => new Blob(['wav'])),
  playSequence: vi.fn(() => Promise.resolve()),
  player: { play: vi.fn(() => Promise.resolve()), playRange: vi.fn(() => Promise.resolve()), stop: vi.fn(), preload: vi.fn(() => Promise.resolve()), peaksFor: vi.fn(() => new Promise(() => {})) },
  ctxClose: vi.fn(() => Promise.resolve()),
}))
vi.mock('../api/client', () => ({ api: h.api }))
vi.mock('../audio/recorder', () => ({
  Recorder: class {
    get sampleRate() { return h.rec.sampleRate }
    start() { return h.rec.start() }
    stop() { return h.rec.stop() }
    snapshot() { return new Float32Array(0) }
  },
  toWav16k: h.toWav16k,
}))
vi.mock('../audio/player', () => ({
  ClipPlayer: class { constructor() { return h.player } },
  playSequence: h.playSequence,
  peaks: () => new Float32Array(4),
}))
vi.mock('../components/TwoTrack', () => ({ default: () => <div data-testid="two-track" /> }))

import Practice from './Practice'

const seg = (id: number, idx: number, text: string): Segment => ({
  id, lesson_id: 1, idx, start_s: idx * 2, end_s: idx * 2 + 2, text, translation: null, words_json: null,
  ref_alignment_json: null, difficulty_flag: false, anki_note_id: null, last_score: null, best_score: null, attempts: 0,
})
const lesson: LessonDetail = {
  id: 1, title: 'Lesson', speaker: '', source_type: 'upload', source_ref: '', duration_s: 4, created_at: '', status: 'ready', error: null,
  segment_count: 2, practised_count: 0, mean_last_score: null, segments: [seg(11, 0, '你好'), seg(12, 1, '再见')],
}
function deferred<T>() {
  let resolve!: (v: T) => void, reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}
const flush = () => act(async () => { for (let i = 0; i < 10; i++) await Promise.resolve() })
const press = (key: string, init: KeyboardEventInit = {}) => fireEvent.keyDown(window, { key, ...init })

function renderPractice() {
  return render(<MemoryRouter initialEntries={['/practice/1']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Routes><Route path="/practice/:id" element={<Practice />} /></Routes></MemoryRouter>)
}

describe('<Practice>', () => {
  const origAudioContext = globalThis.AudioContext
  const origCreate = URL.createObjectURL, origRevoke = URL.revokeObjectURL
  beforeEach(() => {
    vi.clearAllMocks()
    usePractice.setState({ lesson: null, idx: 0, sessionId: null, drawerOpen: true, attemptsThisSegment: 0, lastAttempt: null, recordingNow: false, hint: '' })
    h.api.lessons.get.mockResolvedValue(lesson)
    h.api.sessions.create.mockResolvedValue({ id: 5 })
    h.api.sessions.end.mockResolvedValue({})
    h.api.segments.postAttempt.mockResolvedValue({ id: 99 })
    h.rec.start.mockResolvedValue(undefined)
    h.rec.stop.mockReturnValue(new Float32Array(44100))
    globalThis.AudioContext = class { sampleRate = 44100; close = h.ctxClose } as unknown as typeof AudioContext
    URL.createObjectURL = vi.fn(() => 'blob:take')
    URL.revokeObjectURL = vi.fn()
  })
  afterEach(() => {
    globalThis.AudioContext = origAudioContext
    URL.createObjectURL = origCreate; URL.revokeObjectURL = origRevoke
  })

  it('opens a session on mount and ends it on unmount', async () => {
    const { unmount } = renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    expect(h.api.sessions.create).toHaveBeenCalledWith(1, 'echo')
    await waitFor(() => expect(usePractice.getState().sessionId).toBe(5))
    unmount()
    expect(h.api.sessions.end).toHaveBeenCalledWith(5)
  })

  it('ends a session whose creation resolves only after unmount', async () => {
    const created = deferred<{ id: number }>()
    h.api.sessions.create.mockReturnValue(created.promise)
    const { unmount } = renderPractice()
    unmount()
    created.resolve({ id: 7 })
    await flush()
    expect(h.api.sessions.end).toHaveBeenCalledWith(7)
    expect(usePractice.getState().sessionId).toBeNull()
  })

  it('a denied microphone shows a readable error and leaves Echo idle', async () => {
    h.rec.start.mockRejectedValue(new Error('Microphone permission was denied'))
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('Enter')
    expect(await screen.findByRole('alert')).toHaveTextContent('Microphone permission was denied')
    expect(screen.getByRole('button', { name: '● Enter' })).toBeInTheDocument()
    expect(usePractice.getState().recordingNow).toBe(false)
    press('Enter') // idle, so Enter tries to record again rather than "stopping" a phantom recording
    await flush()
    expect(h.rec.start).toHaveBeenCalledTimes(2)
  })

  it('unmounting while the permission prompt is open stops the recorder once it starts', async () => {
    const started = deferred<void>()
    h.rec.start.mockReturnValue(started.promise)
    const { unmount } = renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('Enter')
    await flush()
    unmount()
    expect(h.rec.stop).not.toHaveBeenCalled()
    started.resolve()
    await flush()
    expect(h.rec.stop).toHaveBeenCalledTimes(1)
    expect(h.ctxClose).toHaveBeenCalled()
    expect(usePractice.getState().recordingNow).toBe(false)
  })

  it('Enter again during the permission prompt abandons the recording and releases the late mic', async () => {
    const started = deferred<void>()
    h.rec.start.mockReturnValue(started.promise)
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('Enter')
    expect(await screen.findByRole('button', { name: '■ stop' })).toBeInTheDocument()
    press('Enter')
    expect(await screen.findByRole('button', { name: '● Enter' })).toBeInTheDocument()
    started.resolve()
    await flush()
    expect(h.rec.stop).toHaveBeenCalledTimes(1)
    expect(h.api.segments.postAttempt).not.toHaveBeenCalled()
  })

  it('Echo: Enter, Enter uploads a take encoded from the real sample rate and plays reference then take', async () => {
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    await waitFor(() => expect(usePractice.getState().sessionId).toBe(5))
    press('Enter')
    expect(await screen.findByRole('button', { name: '■ stop' })).toBeInTheDocument()
    await flush()
    expect(usePractice.getState().recordingNow).toBe(true)
    press('Enter')
    await flush()
    expect(h.toWav16k).toHaveBeenCalledWith(expect.any(Float32Array), 44100)
    expect(h.api.segments.postAttempt).toHaveBeenCalledWith(11, expect.any(Blob), { session_id: 5, mode: 'echo' })
    const [, items] = h.playSequence.mock.calls[0] as unknown as [unknown, { url: string }[]]
    expect(items.map((i) => i.url)).toEqual(['/seg/11.opus', 'blob:take'])
    expect(usePractice.getState()).toMatchObject({ attemptsThisSegment: 1, recordingNow: false, lastAttempt: { id: 99, url: 'blob:take' } })
    expect(screen.getByRole('button', { name: '● Enter' })).toBeInTheDocument()
  })

  it('shows the move-on hint once attempts reach the setting', async () => {
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    for (let i = 0; i < 4; i++) {
      press('Enter'); await flush(); press('Enter'); await flush()
    }
    expect(screen.getByText(/Move on and come back later/)).toBeInTheDocument()
  })

  it('shortcuts are ignored in text fields and with browser modifiers', async () => {
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    fireEvent.keyDown(screen.getByLabelText('Playback speed'), { key: 'l' })
    press('l', { ctrlKey: true })
    expect(usePractice.getState().drawerOpen).toBe(true)
    press('l')
    expect(usePractice.getState().drawerOpen).toBe(false)
  })

  it('ArrowRight moves to the next sentence and cancels playback', async () => {
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('ArrowRight')
    expect(await screen.findByText('再见', { selector: 'p.sentence' })).toBeInTheDocument()
    expect(h.player.stop).toHaveBeenCalled()
    expect(usePractice.getState().idx).toBe(1)
  })
})
