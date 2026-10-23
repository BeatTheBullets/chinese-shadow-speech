import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { FlowRun, LessonDetail, Segment, Take } from '../api/types'
import { currentTake, usePractice } from '../store/practice'
import { useSettings } from '../store/settings'

const h = vi.hoisted(() => ({
  api: {
    lessons: { get: vi.fn(), takes: vi.fn(), flowRuns: vi.fn() },
    attempts: { audioUrl: (id: number) => `/att/${id}.wav` },
    sessions: { create: vi.fn(), end: vi.fn() },
    segments: { audioUrl: (id: number, fmt = 'opus') => `/seg/${id}.${fmt}`, postAttempt: vi.fn(), patch: vi.fn(), resplit: vi.fn(), mergeNext: vi.fn(), clipChanged: vi.fn() },
  },
  exportAndRecord: vi.fn(),
  rec: { start: vi.fn(), stop: vi.fn(), sampleRate: 44100, startTime: 0 },
  clock: { t: 0 }, // AudioContext.currentTime
  toWav16k: vi.fn(() => new Blob(['wav'])),
  playSequence: vi.fn(() => Promise.resolve()),
  takePeaks: new Float32Array(4), // what peaks() returns for a fresh take's You waveform
  player: { play: vi.fn(() => Promise.resolve()), playRange: vi.fn(() => Promise.resolve()), stop: vi.fn(), setVolume: vi.fn(), preload: vi.fn(() => Promise.resolve()), peaksFor: vi.fn<(url: string) => Promise<Float32Array>>(() => new Promise(() => {})) },
  ctxClose: vi.fn(() => Promise.resolve()),
  twoTrack: null as null | { onPlayYouSyllable?: (i: number) => void; onPlaySyllable?: (i: number) => void; onCompareSyllable?: (i: number) => void; youPeaks: Float32Array | null; youDuration: number; score?: unknown },
}))
vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api/client')>()), api: h.api }))
vi.mock('../anki/export', async (importOriginal) => ({ ...(await importOriginal<typeof import('../anki/export')>()), exportAndRecord: h.exportAndRecord }))
vi.mock('../audio/recorder', () => ({
  Recorder: class {
    get sampleRate() { return h.rec.sampleRate }
    start() { return h.rec.start() }
    stop() { return h.rec.stop() }
    snapshot() { return new Float32Array(0) }
    get startTime() { return h.rec.startTime }
    tail() { return new Float32Array(0) }
  },
  toWav16k: h.toWav16k,
}))
vi.mock('../audio/player', () => ({
  ClipPlayer: class { constructor() { return h.player } },
  playSequence: h.playSequence,
  peaks: () => h.takePeaks,
}))
vi.mock('../components/TwoTrack', () => ({
  default: (p: NonNullable<typeof h.twoTrack>) => { h.twoTrack = p; return <div data-testid="two-track" /> },
}))

import { ApiError } from '../api/client'
import { speechBounds } from '../lib/speech'
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
// Entering Flow loads the lesson's stored runs: let that settle inside act().
const enterFlow = async () => { fireEvent.click(screen.getByRole('button', { name: 'Flow' })); await flush() }

function renderPractice(url = '/practice/1') {
  return render(<MemoryRouter initialEntries={[url]} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Routes><Route path="/practice/:id" element={<Practice />} /></Routes></MemoryRouter>)
}

describe('<Practice>', () => {
  it('opens on the sentence named by ?idx= (0-based)', async () => {
    h.api.lessons.get.mockResolvedValue(lesson)
    renderPractice('/practice/1?idx=1')
    await screen.findByText('再见', { selector: 'p.sentence' })
    expect(usePractice.getState().idx).toBe(1)
  })


  it('Echo: the uploaded take\u2019s score reaches the You track and the sentence\u2019s last score', async () => {
    const score = { overall: 0.8, tone_overall: 0.8, segmental_overall: null, rate_ratio: 1, ref_contour: null, usr_contour: null, syllables: [], warnings: [] }
    h.api.segments.postAttempt.mockResolvedValue({ id: 99, score_json: score })
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    await waitFor(() => expect(usePractice.getState().sessionId).toBe(5))
    press('Enter'); await screen.findByRole('button', { name: 'Stop (Enter)' }); await flush()
    press('Enter'); await flush()
    await waitFor(() => expect(h.twoTrack?.score).toEqual(score))
    expect(usePractice.getState().lesson!.segments[0]).toMatchObject({ last_score: 0.8, attempts: 1 })
  })

  it('Echo is compact: under the card one slim stage line while idle and listening (no reserved room), tight page spacing', async () => {
    h.player.play.mockImplementation(() => new Promise(() => {}))
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    const cue = () => screen.getByTestId('stage-cue')
    expect(cue()).toHaveClass('min-h-8'); expect(cue()).not.toHaveClass('min-h-28')
    expect(screen.getByTestId('stage').parentElement).toHaveClass('space-y-3')
    press(' ')
    await waitFor(() => expect(screen.getByTestId('stage')).toHaveAttribute('data-stage', 'listen'))
    expect(cue()).toHaveClass('min-h-8'); expect(cue()).not.toHaveClass('min-h-28')
    expect(screen.queryByTestId('wave-slot')).toBeNull()
  })

  it('a gated take explains itself in the hint line', async () => {
    const score = { overall: null, tone_overall: null, segmental_overall: null, rate_ratio: null, ref_contour: null, usr_contour: null, syllables: [], warnings: ['too_quiet'] }
    h.api.segments.postAttempt.mockResolvedValue({ id: 99, score_json: score })
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('Enter'); await screen.findByRole('button', { name: 'Stop (Enter)' }); await flush()
    press('Enter'); await flush()
    expect(await screen.findByText('Too quiet — not scored. Move closer to the mic.')).toBeInTheDocument()
  })

  it('a take of other words shows what was heard in the hint line', async () => {
    const score = { overall: null, tone_overall: null, segmental_overall: null, rate_ratio: null, ref_contour: null, usr_contour: null, syllables: [], warnings: ['different_words'], heard_text: '我是学生' }
    h.api.segments.postAttempt.mockResolvedValue({ id: 99, score_json: score })
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('Enter'); await screen.findByRole('button', { name: 'Stop (Enter)' }); await flush()
    press('Enter'); await flush()
    expect(await screen.findByText('Heard different words — not scored. Heard: 我是学生')).toBeInTheDocument()
  })

  it('a scored take whose words partly differed is scored and says what was heard', async () => {
    const score = { overall: 0.7, tone_overall: 0.7, segmental_overall: null, rate_ratio: 1, ref_contour: null, usr_contour: null, syllables: [], warnings: [], notices: ['words_differ'], heard_text: '你号' }
    h.api.segments.postAttempt.mockResolvedValue({ id: 99, score_json: score })
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('Enter'); await screen.findByRole('button', { name: 'Stop (Enter)' }); await flush()
    press('Enter'); await flush()
    expect(await screen.findByText('Some words sounded different — heard: 你号')).toBeInTheDocument()
    expect(usePractice.getState().lesson!.segments[0]).toMatchObject({ last_score: 0.7 })
  })

  const gated = { overall: null, tone_overall: null, segmental_overall: null, rate_ratio: null, ref_contour: null, usr_contour: null, syllables: [], warnings: ['too_quiet'] }
  const scored = { ...gated, overall: 0.8, tone_overall: 0.8, warnings: [] }
  const QUIET = 'Too quiet — not scored. Move closer to the mic.'

  it('a gated take that uploads after moving on does not explain itself under the next sentence', async () => {
    const pending = deferred<{ id: number; score_json: typeof gated }>()
    h.api.segments.postAttempt.mockReturnValue(pending.promise)
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('Enter'); await screen.findByRole('button', { name: 'Stop (Enter)' }); await flush()
    press('Enter'); await flush()
    press('ArrowRight'); await screen.findByText('再见', { selector: 'p.sentence' })
    await act(async () => { pending.resolve({ id: 99, score_json: gated }) }); await flush()
    expect(screen.queryByText(QUIET)).toBeNull()
    expect(usePractice.getState().hint).toBe('')
  })

  it('a scored retake clears the gate warning but keeps the move-on hint', async () => {
    h.api.segments.postAttempt.mockResolvedValueOnce({ id: 1, score_json: gated }).mockResolvedValueOnce({ id: 2, score_json: scored })
      .mockResolvedValueOnce({ id: 3, score_json: gated }).mockResolvedValueOnce({ id: 4, score_json: scored })
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    const take = async () => { press('Enter'); await flush(); press('Enter'); await flush() }
    await take()
    expect(await screen.findByText(QUIET)).toBeInTheDocument()
    await take()
    await waitFor(() => expect(screen.queryByText(QUIET)).toBeNull())
    await take()
    expect(await screen.findByText(QUIET)).toBeInTheDocument()
    await take() // the fourth attempt reaches moveOnAfter (4): the move-on hint, then a scored upload
    await waitFor(() => expect(screen.queryByText(QUIET)).toBeNull())
    expect(screen.getByText(/Move on and come back later/)).toBeInTheDocument()
  })

  it('a clean retake clears the words-differ notice', async () => {
    const differ = { ...scored, notices: ['words_differ'], heard_text: '你号' }
    h.api.segments.postAttempt.mockResolvedValueOnce({ id: 1, score_json: differ }).mockResolvedValueOnce({ id: 2, score_json: { ...scored, notices: [] } })
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    const take = async () => { press('Enter'); await flush(); press('Enter'); await flush() }
    await take()
    expect(await screen.findByText('Some words sounded different — heard: 你号')).toBeInTheDocument()
    await take()
    await waitFor(() => expect(screen.queryByText(/Some words sounded different/)).toBeNull())
  })

  it('stored takes bring their score back when the lesson is reopened', async () => {
    const score = { overall: 0.6, tone_overall: 0.6, segmental_overall: null, rate_ratio: 1, ref_contour: null, usr_contour: null, syllables: [], warnings: [] }
    h.api.lessons.takes.mockResolvedValue([{ segment_id: 11, attempt_id: 7, mode: 'echo', created_at: '', duration_s: 1, score_json: score }])
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    await waitFor(() => expect(h.twoTrack?.score).toEqual(score))
  })
  it('old chorus/guided takes still render with their labels', async () => {
    h.api.lessons.takes.mockResolvedValue([{ segment_id: 11, attempt_id: 7, mode: 'chorus', created_at: '', duration_s: 1.5 },
      { segment_id: 12, attempt_id: 8, mode: 'guided', created_at: '', duration_s: 2.5 }])
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    await waitFor(() => expect(h.twoTrack?.youDuration).toBe(1.5))
    expect(usePractice.getState().storedTakes[11]).toMatchObject({ id: 7, url: '/att/7.wav' })
    press('ArrowRight'); await screen.findByText('再见', { selector: 'p.sentence' })
    await waitFor(() => expect(h.twoTrack?.youDuration).toBe(2.5))
    expect(screen.getAllByRole('button').map((b) => b.textContent)).not.toContain('Chorus')
  })

  it('C does nothing: no playback, no microphone, no upload', async () => {
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    await waitFor(() => expect(usePractice.getState().sessionId).toBe(5))
    press('c'); await flush()
    expect(h.player.play).not.toHaveBeenCalled()
    expect(h.rec.start).not.toHaveBeenCalled()
    expect(h.api.segments.postAttempt).not.toHaveBeenCalled()
    expect(screen.queryByText('Use headphones — the mic would pick up the reference')).toBeNull()
  })

  const origAudioContext = globalThis.AudioContext
  const origCreate = URL.createObjectURL, origRevoke = URL.revokeObjectURL
  beforeEach(() => {
    vi.clearAllMocks()
    usePractice.setState({ lesson: null, idx: 0, mode: 'echo', sessionId: null, drawerOpen: false, attemptsThisSegment: 0, lastAttempt: null, recordingNow: false, hint: '', storedTakes: {} })
    // helpSeen: the help would otherwise open on every render and switch the shortcuts off. The volumes are reset here,
    // not at the end of a test, so no store update reaches a page that is still mounted (act() warnings).
    useSettings.setState({ helpSeen: true, referenceVolume: 1, guideLevel: 0.5, textPrefs: {} })
    h.api.lessons.get.mockResolvedValue(lesson)
    h.api.lessons.takes.mockResolvedValue([])
    h.api.lessons.flowRuns.mockResolvedValue([])
    h.api.sessions.create.mockResolvedValue({ id: 5 })
    h.api.sessions.end.mockResolvedValue({})
    h.api.segments.postAttempt.mockResolvedValue({ id: 99 })
    h.rec.start.mockResolvedValue(undefined)
    h.rec.stop.mockReturnValue(new Float32Array(44100))
    h.rec.startTime = 0; h.clock.t = 0
    h.player.play.mockImplementation(() => Promise.resolve())
    h.player.stop.mockImplementation(() => {})
    h.player.peaksFor.mockImplementation(() => new Promise(() => {}))
    h.playSequence.mockImplementation(() => Promise.resolve())
    h.takePeaks = new Float32Array(4)
    globalThis.AudioContext = class { sampleRate = 44100; close = h.ctxClose; get currentTime() { return h.clock.t } } as unknown as typeof AudioContext
    URL.createObjectURL = vi.fn(() => 'blob:take')
    URL.revokeObjectURL = vi.fn()
  })
  afterEach(() => {
    cleanup() // unmount (freeing blob: URLs) while the URL and AudioContext stubs are still in place
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
    expect(screen.getByRole('button', { name: 'Record (Enter)' })).toBeInTheDocument()
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
    expect(await screen.findByRole('button', { name: 'Stop (Enter)' })).toBeInTheDocument()
    press('Enter')
    expect(await screen.findByRole('button', { name: 'Record (Enter)' })).toBeInTheDocument()
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
    expect(await screen.findByRole('button', { name: 'Stop (Enter)' })).toBeInTheDocument()
    await flush()
    expect(usePractice.getState().recordingNow).toBe(true)
    press('Enter')
    await flush()
    expect(h.toWav16k).toHaveBeenCalledWith(expect.any(Float32Array), 44100)
    expect(h.api.segments.postAttempt).toHaveBeenCalledWith(11, expect.any(Blob), { session_id: 5, mode: 'echo' })
    const [, items] = h.playSequence.mock.calls[0] as unknown as [unknown, { url: string }[]]
    expect(items.map((i) => i.url)).toEqual(['/seg/11.opus', 'blob:take'])
    expect(usePractice.getState()).toMatchObject({ attemptsThisSegment: 1, recordingNow: false, lastAttempt: { id: 99, url: 'blob:take' } })
    expect(screen.getByRole('button', { name: 'Record (Enter)' })).toBeInTheDocument()
  })

  it('a take refused while the lesson is rebuilt says so and stays playable', async () => {
    h.api.segments.postAttempt.mockRejectedValue(new ApiError(409, 'Conflict', '{"detail":"this lesson is being rebuilt — try again in a moment"}', 'this lesson is being rebuilt — try again in a moment'))
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    await waitFor(() => expect(usePractice.getState().sessionId).toBe(5))
    press('Enter')
    await screen.findByRole('button', { name: 'Stop (Enter)' })
    await flush()
    press('Enter')
    expect(await screen.findByRole('alert')).toHaveTextContent('Upload failed: this lesson is being rebuilt — try again in a moment')
    expect(usePractice.getState().lastAttempt).toMatchObject({ id: 0, url: 'blob:take' })
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
    fireEvent.click(screen.getByRole('button', { name: 'Sound' }))
    fireEvent.keyDown(screen.getByLabelText('Playback speed'), { key: 'l' })
    press('l', { ctrlKey: true })
    expect(usePractice.getState().drawerOpen).toBe(false)
    press('l')
    expect(usePractice.getState().drawerOpen).toBe(true)
  })

  it('a take under 0.2 s is discarded: no upload, no attempt counted, back to idle', async () => {
    h.rec.stop.mockReturnValue(new Float32Array(4410)) // 0.1 s at 44.1 kHz
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('Enter'); await flush(); press('Enter'); await flush()
    expect(h.api.segments.postAttempt).not.toHaveBeenCalled()
    expect(h.playSequence).not.toHaveBeenCalled()
    expect(usePractice.getState()).toMatchObject({ attemptsThisSegment: 0, lastAttempt: null, recordingNow: false })
    expect(screen.getByRole('alert')).toHaveTextContent(/Too short/)
    expect(screen.getByRole('button', { name: 'Record (Enter)' })).toBeInTheDocument()
  })

  // 100 buckets, voice in 20..60: on a 1 s take that is 0.05..0.76 s with the padding.
  const voiced = () => Float32Array.from({ length: 100 }, (_, b) => (b >= 20 && b <= 60 ? 0.5 : 0.001))

  it('the take plays back from where the voice starts, after recording and on R', async () => {
    h.takePeaks = voiced()
    const b = speechBounds(h.takePeaks, 1)!
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('Enter'); await flush(); press('Enter'); await flush()
    const [, items] = h.playSequence.mock.calls[0] as unknown as [unknown, { url: string; from?: number; to?: number }[]]
    expect(items[0]).not.toHaveProperty('from')
    expect(items[1]).toMatchObject({ url: 'blob:take', from: b.from, to: b.to })
    press('r'); await flush()
    expect(h.player.play).not.toHaveBeenCalled()
    expect(h.player.playRange).toHaveBeenCalledWith('blob:take', 1, b.from, b.to, expect.any(Function))
    expect(h.twoTrack!.youPeaks).toBe(h.takePeaks) // the waveform stays the whole take
  })

  it('R plays a stored take from speechBounds().from of its waveform; with no clear voice, the whole take', async () => {
    const p = Float32Array.from({ length: 400 }, (_, i) => (i >= 100 && i < 300 ? 0.4 : 0))
    h.api.lessons.takes.mockResolvedValue([{ segment_id: 11, attempt_id: 77, mode: 'echo', created_at: '', duration_s: 2 },
      { segment_id: 12, attempt_id: 78, mode: 'echo', created_at: '', duration_s: 2 }])
    h.player.peaksFor.mockImplementation((url: string) => Promise.resolve(url === '/att/77.wav' ? p : new Float32Array(400)))
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    await waitFor(() => expect(h.twoTrack!.youPeaks).toBe(p))
    press('r'); await flush()
    const b = speechBounds(p, 2)!
    expect(b.from).toBeCloseTo(0.35, 5)
    expect(h.player.playRange).toHaveBeenCalledWith('/att/77.wav', 1, b.from, b.to, expect.any(Function))
    press('ArrowRight'); await screen.findByText('再见', { selector: 'p.sentence' })
    await waitFor(() => expect(h.twoTrack!.youPeaks).not.toBeNull())
    press('r'); await flush()
    expect(h.player.play).toHaveBeenCalledWith('/att/78.wav', 1, expect.any(Function))
  })

  const dropped = { id: null, dropped: true, score_json: gated }

  it('a dropped take shows the warning, has no take or replay, and the attempt count is unchanged', async () => {
    h.api.segments.postAttempt.mockResolvedValue(dropped)
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('Enter'); await flush(); press('Enter'); await flush()
    expect(await screen.findByText(QUIET)).toBeInTheDocument()
    expect(usePractice.getState()).toMatchObject({ lastAttempt: null, attemptsThisSegment: 0, storedTakes: {}, practised: [] })
    expect(usePractice.getState().lesson!.segments[0].attempts).toBe(0)
    expect(h.twoTrack!.youPeaks).toBeNull()
    expect(h.twoTrack!.youDuration).toBe(0)
    h.player.play.mockClear()
    press('r'); await flush()
    expect(h.player.play).not.toHaveBeenCalled()
    expect(h.player.playRange).not.toHaveBeenCalled()
  })

  it('a take dropped while the reference plays back stops that playback before the take', async () => {
    const pending = deferred<typeof dropped>()
    h.api.segments.postAttempt.mockReturnValue(pending.promise)
    let signal: AbortSignal | undefined
    h.playSequence.mockImplementation(((_p: unknown, _items: unknown, _gap: unknown, s: AbortSignal) => { signal = s; return new Promise(() => {}) }) as unknown as () => Promise<void>)
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('Enter'); await flush(); press('Enter'); await flush()
    expect(signal!.aborted).toBe(false)
    expect(usePractice.getState().attemptsThisSegment).toBe(1)
    await act(async () => { pending.resolve(dropped) }); await flush()
    expect(signal!.aborted).toBe(true)
    expect(usePractice.getState()).toMatchObject({ lastAttempt: null, attemptsThisSegment: 0 })
    expect(await screen.findByText(QUIET)).toBeInTheDocument()
  })

  it('the take uploads to the sentence the recording started on even if the store moved meanwhile', async () => {
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('Enter'); await flush()
    act(() => { usePractice.setState({ idx: 1 }) }) // stale-store window: idx changes without a cancel
    press('Enter'); await flush()
    expect(h.api.segments.postAttempt).toHaveBeenCalledWith(11, expect.any(Blob), expect.objectContaining({ mode: 'echo' }))
    expect(usePractice.getState().lastAttempt).toBeNull()
    expect(h.playSequence).not.toHaveBeenCalled()
  })

  it('keys do nothing while the store still holds another lesson', async () => {
    const pending = deferred<LessonDetail>()
    h.api.lessons.get.mockReturnValue(pending.promise)
    usePractice.setState({ lesson: { ...lesson, id: 2 } })
    renderPractice()
    press('Enter'); press('l')
    await flush()
    expect(h.rec.start).not.toHaveBeenCalled()
    expect(usePractice.getState().drawerOpen).toBe(false)
  })

  describe('stored takes', () => {
    const take = (segment_id: number, attempt_id: number, duration_s: number): Take => ({ segment_id, attempt_id, mode: 'flow', created_at: '2026-10-07T09:00:00Z', duration_s })
    const played = () => h.player.play.mock.calls.map((c) => (c as unknown[])[0])

    it("R replays the sentence's stored take when the lesson is opened again; the You track shows it, per sentence", async () => {
      h.api.lessons.takes.mockResolvedValue([take(11, 77, 1.5), take(12, 78, 2.5)])
      const p77 = new Float32Array([0, 0]) // no clear voice: R plays the whole take
      h.player.peaksFor.mockImplementation((url: string) => (url === '/att/77.wav' ? Promise.resolve(p77) : new Promise(() => {})))
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      expect(h.api.lessons.takes).toHaveBeenCalledWith(1)
      await waitFor(() => expect(h.twoTrack!.youPeaks).toBe(p77))
      expect(h.twoTrack!.youDuration).toBe(1.5)
      press('r'); await flush()
      expect(played()).toEqual(['/att/77.wav'])
      press('ArrowRight')
      await screen.findByText('再见', { selector: 'p.sentence' })
      await waitFor(() => expect(h.twoTrack!.youDuration).toBe(2.5))
      expect(h.twoTrack!.youPeaks).toBeNull()
      press('r'); await flush()
      expect(played()).toEqual(['/att/77.wav', '/att/78.wav'])
    })

    it('R without any take of the sentence does nothing', async () => {
      h.api.lessons.takes.mockResolvedValue([take(12, 78, 2.5)])
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      await waitFor(() => expect(usePractice.getState().storedTakes[12]).toBeDefined())
      press('r'); await flush()
      expect(h.player.play).not.toHaveBeenCalled()
      expect(h.twoTrack!.youDuration).toBe(0)
    })

    it('a takes answer arriving after a newer upload does not bring the older take back', async () => {
      const takes = deferred<Take[]>()
      h.api.lessons.takes.mockReturnValue(takes.promise)
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      press('Enter'); await flush(); press('Enter'); await flush()
      await waitFor(() => expect(usePractice.getState().storedTakes[11]).toMatchObject({ id: 99 }))
      await act(async () => { takes.resolve([take(11, 77, 1.5), take(12, 78, 2.5)]) })
      expect(usePractice.getState().storedTakes[11]).toMatchObject({ id: 99, url: '/att/99.wav' })
      expect(usePractice.getState().storedTakes[12]).toMatchObject({ id: 78 })
    })

    it("a take recorded now is the one R replays, and stays the sentence's take after moving away and back", async () => {
      h.api.lessons.takes.mockResolvedValue([take(11, 77, 1.5)])
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      await waitFor(() => expect(usePractice.getState().storedTakes[11]).toBeDefined())
      press('Enter'); await flush(); press('Enter'); await flush()
      press('r'); await flush()
      expect(played()).toEqual(['blob:take'])
      press('ArrowRight'); await screen.findByText('再见', { selector: 'p.sentence' })
      press('ArrowLeft'); await screen.findByText('你好', { selector: 'p.sentence' })
      expect(h.twoTrack!.youDuration).toBe(1)
      press('r'); await flush()
      expect(played()).toEqual(['blob:take', '/att/99.wav'])
    })
  })

  describe('syllable click', () => {
    const aligned: LessonDetail = {
      ...lesson,
      segments: [{ ...seg(11, 0, '你好'), start_s: 10, end_s: 12, ref_alignment_json: [{ ch: '你', start: 10.2, end: 10.5, conf: 1 }, { ch: '好', start: 10.5, end: 11.25, conf: 1 }] }],
    }
    const sleep = (ms: number) => act(() => new Promise((r) => setTimeout(r, ms)))
    // jsdom does no layout: each character gets a 40 px box at 40 px × its offset, so a click at x = 40 i + 20 is on character i.
    const origRects = Range.prototype.getClientRects
    beforeEach(() => {
      h.api.lessons.get.mockResolvedValue(aligned)
      Range.prototype.getClientRects = function (this: Range) { return [{ left: this.startOffset * 40, top: 0, width: 40, height: 40 }] as unknown as DOMRectList }
    })
    afterEach(() => { Range.prototype.getClientRects = origRects })
    const clickChar = (i: number) => act(() => { fireEvent.click(screen.getByText('你好', { selector: 'p.sentence' }), { clientX: 40 * i + 20, clientY: 20 }) })

    it('clicking a character on the sentence card plays the clip-relative span of its syllable once', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      clickChar(1)
      await flush()
      expect(h.player.playRange).toHaveBeenCalledTimes(1)
      const [url, rate, from, to] = h.player.playRange.mock.calls[0] as unknown as [string, number, number, number]
      expect([url, rate]).toEqual(['/seg/11.wav', 1])
      expect(from).toBeCloseTo(0.5, 5); expect(to).toBeCloseTo(1.25, 5)
      await sleep(600)
      expect(h.player.playRange).toHaveBeenCalledTimes(1) // no loop
    })

    it('clicking again plays it again; a click while recording does nothing', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      clickChar(0); await flush()
      clickChar(0); await flush()
      expect(h.player.playRange).toHaveBeenCalledTimes(2)
      // The text stays up while recording here, so there is a character to click.
      const practice = useSettings.getState().practice
      useSettings.setState({ practice: { ...practice, hideTextWhileRecording: false } })
      try {
        press('Enter'); await flush()
        clickChar(0); await flush()
        expect(h.player.playRange).toHaveBeenCalledTimes(2)
      } finally { cleanup(); useSettings.setState({ practice }) }
    })

    it('a verdict cell’s speaker button plays that syllable of the reference; its character plays the speaker, a pause, then you', async () => {
      const usr_contour = { t0_s: 0, step_ms: 10, f0_st: [], spans: [[0.1, 0.4], [0.4, 0.9]] }
      const syl = (status: string) => ({ ch: '你', pinyin: 'nǐ', tone: 3, target_tone: 3, heard_tone: 3, status, tone_score: 0.9, p_target: 0.9, contour: 0.9 })
      const score = { overall: 0.8, tone_overall: 0.8, segmental_overall: null, rate_ratio: 1, ref_contour: null, usr_contour, syllables: [syl('ok'), syl('missing')], warnings: [] }
      h.api.segments.postAttempt.mockResolvedValue({ id: 99, score_json: score })
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      await waitFor(() => expect(usePractice.getState().sessionId).toBe(5))
      press('Enter'); await screen.findByRole('button', { name: 'Stop (Enter)' }); await flush()
      press('Enter'); await flush()
      await waitFor(() => expect(h.twoTrack?.score).toEqual(score))
      const url = currentTake(usePractice.getState())!.url
      h.player.playRange.mockClear(); h.playSequence.mockClear()
      act(() => h.twoTrack!.onPlaySyllable!(1)); await flush()
      expect(h.player.playRange).toHaveBeenCalledTimes(1)
      const [rurl, rate, from, to] = h.player.playRange.mock.calls[0] as unknown as [string, number, number, number]
      expect([rurl, rate]).toEqual(['/seg/11.wav', 1]); expect(from).toBeCloseTo(0.5, 5); expect(to).toBeCloseTo(1.25, 5)
      act(() => h.twoTrack!.onCompareSyllable!(0)); await flush()
      expect(h.playSequence).toHaveBeenCalledTimes(1)
      const [, items, gap] = h.playSequence.mock.calls[0] as unknown as [unknown, { url: string; rate: number; from: number; to: number }[], number]
      expect(gap).toBe(250)
      expect(items.map((i) => [i.url, i.rate])).toEqual([['/seg/11.wav', 1], [url, 1]])
      expect(items[0].from).toBeCloseTo(0.2, 5); expect(items[0].to).toBeCloseTo(0.5, 5)
      expect([items[1].from, items[1].to]).toEqual([0.1, 0.4])
      // A missing syllable has nothing of yours: its character plays the speaker alone.
      act(() => h.twoTrack!.onCompareSyllable!(1)); await flush()
      const [, only] = h.playSequence.mock.calls[1] as unknown as [unknown, { url: string }[]]
      expect(only.map((i) => i.url)).toEqual(['/seg/11.wav'])
    })
  })

  it('clicking a You cell plays that span of the take; missing and unvoiced cells play nothing', async () => {
    const usr_contour = { t0_s: 0, step_ms: 10, f0_st: [], spans: [[0.1, 0.4], [0.4, 0.9], [0.9, 0.91]] }
    const syl = (status: string) => ({ ch: '你', pinyin: 'nǐ', tone: 3, target_tone: 3, heard_tone: 3, status, tone_score: 0.9, p_target: 0.9, contour: 0.9 })
    const score = { overall: 0.8, tone_overall: 0.8, segmental_overall: null, rate_ratio: 1, ref_contour: null, usr_contour, syllables: [syl('ok'), syl('unvoiced'), syl('missing')], warnings: [] }
    h.api.segments.postAttempt.mockResolvedValue({ id: 99, score_json: score })
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    await waitFor(() => expect(usePractice.getState().sessionId).toBe(5))
    press('Enter'); await screen.findByRole('button', { name: 'Stop (Enter)' }); await flush()
    press('Enter'); await flush()
    await waitFor(() => expect(h.twoTrack?.score).toEqual(score))
    const url = currentTake(usePractice.getState())!.url
    act(() => h.twoTrack!.onPlayYouSyllable!(0)); await flush()
    expect(h.player.playRange).toHaveBeenCalledTimes(1)
    expect(h.player.playRange).toHaveBeenCalledWith(url, 1, 0.1, 0.4, expect.any(Function))
    act(() => h.twoTrack!.onPlayYouSyllable!(1)); await flush()
    act(() => h.twoTrack!.onPlayYouSyllable!(2)); await flush()
    expect(h.player.playRange).toHaveBeenCalledTimes(1)
  })

  it('ArrowRight moves to the next sentence and cancels playback', async () => {
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('ArrowRight')
    expect(await screen.findByText('再见', { selector: 'p.sentence' })).toBeInTheDocument()
    expect(h.player.stop).toHaveBeenCalled()
    expect(usePractice.getState().idx).toBe(1)
  })
  // A player whose clips advance the recording clock by `secs` and end on their own, or (hold) only when stopped.
  function clipsTake(secs: number, hold: (n: number) => boolean = () => false) {
    const waiting: (() => void)[] = []
    let n = 0
    h.player.play.mockImplementation(() => {
      const mine = ++n
      if (!hold(mine)) { h.clock.t += secs; return Promise.resolve() }
      return new Promise<void>((r) => { waiting.push(r) })
    })
    h.player.stop.mockImplementation(() => { waiting.splice(0).forEach((r) => r()) })
  }
  const sleepMs = (ms: number) => act(() => new Promise((r) => setTimeout(r, ms)))
  const uploads = () => (h.api.segments.postAttempt.mock.calls as unknown as [number, Blob, { mode: string }][]).map(([sid, , o]) => [sid, o.mode])
  const wavLengths = () => (h.toWav16k.mock.calls as unknown as [Float32Array, number][]).map(([x, sr]) => [x.length, sr])

  describe('Flow', () => {
    async function startFlow(sub: 'after' | 'along' = 'along') {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      await waitFor(() => expect(usePractice.getState().sessionId).toBe(5))
      await enterFlow()
      fireEvent.click(screen.getByRole('button', { name: sub }))
      fireEvent.click(screen.getByRole('button', { name: 'Start flow (Enter)' }))
    }

    it('choosing Flow shows the Flow screen at once: the start sentence on the stage, a windowed transcript, the settings and a pulsing Start; Enter starts the run', async () => {
      clipsTake(2, () => true)
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      await enterFlow()
      expect(screen.getByTestId('flow-transcript')).toBeInTheDocument()
      expect(screen.getByTestId('flow-current')).toContainElement(screen.getByTestId('stage'))
      expect(screen.getByTestId('stage')).toHaveAttribute('data-stage', 'idle')
      expect(screen.getByTestId('stage')).toHaveTextContent('你好')
      expect(screen.getAllByTestId('flow-line').map((l) => l.textContent)).toEqual(['2再见'])
      expect(screen.queryByTestId('two-track')).toBeNull()                       // not the Echo screen
      expect(screen.getByRole('button', { name: 'after' })).toHaveAttribute('aria-pressed', 'true')
      expect(screen.getByRole('combobox', { name: 'Flow from' })).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Start flow (Enter)' })).toHaveClass('pulse-next')
      expect(screen.getByTestId('stage')).not.toHaveTextContent(/Ready|Enter/)
      fireEvent.click(screen.getByRole('button', { name: 'along' }))
      press('Enter')
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(1))
      expect(h.rec.start).toHaveBeenCalledTimes(1)
      expect(screen.getByTestId('stage')).toHaveTextContent('Speak along')
      expect(screen.getByRole('button', { name: 'Stop (Enter)' })).not.toHaveClass('pulse-next')
      press('Enter')
      expect(await screen.findByText(/Flow finished/)).toBeInTheDocument()
    })

    it('before a run one sentence drives the stage and the bar: Flow opens on the sentence you are on; ›, Flow from, Space and F all agree', async () => {
      h.api.lessons.get.mockResolvedValue({ ...lesson, passages: [{ idx: 0, title: 'P1', start_s: 0, end_s: 4, segment_ids: [11, 12], done: false }] })
      h.api.segments.patch.mockResolvedValue(seg(12, 1, '再见'))
      h.player.play.mockImplementation(() => new Promise(() => {}))
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      press('ArrowRight')
      expect(await screen.findByText('再见', { selector: 'p.sentence' })).toBeInTheDocument()
      await enterFlow()
      const from = () => (screen.getByRole('combobox', { name: 'Flow from' }) as HTMLSelectElement).value
      const to = () => (screen.getByRole('combobox', { name: 'Flow to' }) as HTMLSelectElement).value
      expect(screen.getByTestId('stage')).toHaveTextContent('再见')              // Echo → Flow keeps the sentence (12)…
      expect(screen.getByTestId('position')).toHaveTextContent('2 / 2')          // …the bar stays on it…
      expect([from(), to()]).toEqual(['1', '1'])                                  // …the run starts there and ends with the passage
      fireEvent.change(screen.getByRole('combobox', { name: 'Flow from' }), { target: { value: '0' } })
      await waitFor(() => expect(screen.getByTestId('stage')).toHaveTextContent('你好'))
      expect(screen.getByTestId('position')).toHaveTextContent('1 / 2')
      expect(from()).toBe('0')
      press('ArrowRight')                                                         // › inside the passage: stage and bar move together
      await waitFor(() => expect(screen.getByTestId('stage')).toHaveTextContent('再见'))
      expect(screen.getByTestId('position')).toHaveTextContent('2 / 2')
      expect(from()).toBe('1')
      press(' ')
      await waitFor(() => expect(screen.getByTestId('stage')).toHaveAttribute('data-stage', 'listen'))
      expect(h.player.play).toHaveBeenLastCalledWith('/seg/12.opus', 1, expect.any(Function))
      press('f'); await flush()
      expect(h.api.segments.patch).toHaveBeenCalledWith(12, { difficulty_flag: true })
      fireEvent.click(screen.getByRole('button', { name: 'Echo' })); await flush()  // back to Echo: still on the same sentence
      expect(screen.getByTestId('position')).toHaveTextContent('2 / 2')
      expect(screen.getByText('再见', { selector: 'p.sentence' })).toBeInTheDocument()
    })

    it('a chosen "to" the current sentence moves past goes back to the default (the end of the passage)', async () => {
      h.api.lessons.get.mockResolvedValue({ ...lesson, passages: [{ idx: 0, title: 'P1', start_s: 0, end_s: 4, segment_ids: [11, 12], done: false }] })
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      await enterFlow()
      const to = () => (screen.getByRole('combobox', { name: 'Flow to' }) as HTMLSelectElement).value
      fireEvent.change(screen.getByRole('combobox', { name: 'Flow to' }), { target: { value: '0' } })
      expect(to()).toBe('0')
      press('ArrowRight')
      await waitFor(() => expect(screen.getByTestId('position')).toHaveTextContent('2 / 2'))
      expect(to()).toBe('1')
    })

    it('along plays every clip at the guide level and hints at headphones', async () => {
      useSettings.setState({ referenceVolume: 0.8, guideLevel: 0.5 })
      const atPlay: number[] = []
      h.player.play.mockImplementation(() => { atPlay.push(h.player.setVolume.mock.lastCall![0] as number); h.clock.t += 2; return Promise.resolve() })
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('along')
      await screen.findByText(/Flow finished/)
      expect(atPlay).toHaveLength(2)
      atPlay.forEach((v) => expect(v).toBeCloseTo(0.4))
      expect(screen.getByText('Use headphones — the mic would pick up the reference')).toBeInTheDocument()
    })

    it('along: records once, plays the range back to back, uploads one flow slice per sentence and shows the summary', async () => {
      clipsTake(2)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('along')
      expect(await screen.findByText(/Flow finished · 2 sentences/)).toBeInTheDocument()
      expect(screen.queryByTestId('stage')).toBeNull()       // no empty idle stage above the summary
      await waitFor(() => expect(h.api.segments.postAttempt).toHaveBeenCalledTimes(2))
      expect(h.rec.start).toHaveBeenCalledTimes(1)
      expect(h.player.play.mock.calls.map((c) => (c as unknown[])[0])).toEqual(['/seg/11.opus', '/seg/12.opus'])
      expect(uploads()).toEqual([[11, 'flow'], [12, 'flow']])
      expect(h.api.segments.postAttempt).toHaveBeenCalledWith(11, expect.any(Blob), { session_id: 5, mode: 'flow' })
      // clip 1 played 0–2 s, clip 2 2–4 s; each slice spans its clip with 150 ms slack
      expect(wavLengths()).toEqual([[Math.floor(2.15 * 44100), 44100], [Math.floor(4.15 * 44100) - Math.floor(1.85 * 44100), 44100]])
      await waitFor(() => expect(h.api.lessons.get).toHaveBeenCalledTimes(2)) // scores refreshed
      expect(usePractice.getState().recordingNow).toBe(false)
      fireEvent.click(screen.getAllByRole('button', { name: 'Listen + me' })[1])
      const [, items] = h.playSequence.mock.calls.at(-1) as unknown as [unknown, { url: string; rate: number }[]]
      expect(items).toEqual([{ url: '/seg/12.opus', rate: 1 }, { url: 'blob:take', rate: 1 }])
    })

    it("the summary's Echo on a row opens that sentence in Echo", async () => {
      clipsTake(2)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('along')
      expect(await screen.findByText(/Flow finished · 2 sentences/)).toBeInTheDocument()
      const rows = screen.getAllByRole('button', { name: 'Listen + me' }).map((b) => b.parentElement!)
      fireEvent.click(within(rows[1]).getByRole('button', { name: 'Open in Echo' }))
      await waitFor(() => expect(usePractice.getState().mode).toBe('echo'))
      expect(usePractice.getState().idx).toBe(1)
      expect(await screen.findByText('再见', { selector: 'p.sentence' })).toBeInTheDocument()
      expect(h.rec.start).toHaveBeenCalledTimes(1) // only the Flow run's recording: Echo waits for Enter
    })

    it('a flow slice refused while the lesson is rebuilt says so', async () => {
      h.api.segments.postAttempt.mockRejectedValue(new ApiError(409, 'Conflict', '{"detail":"this lesson is being rebuilt — try again in a moment"}', 'this lesson is being rebuilt — try again in a moment'))
      clipsTake(2)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('along')
      expect(await screen.findByText(/Flow finished · 2 sentences/)).toBeInTheDocument()
      expect(await screen.findByRole('alert')).toHaveTextContent('Upload failed: this lesson is being rebuilt — try again in a moment')
    })

    it('a dropped flow slice leaves its sentence without a take in the run', async () => {
      h.api.segments.postAttempt.mockImplementation((id: number) => Promise.resolve(id === 11 ? { id: null, dropped: true, score_json: gated } : { id: 99, score_json: scored }))
      h.api.lessons.get.mockResolvedValueOnce(lesson).mockReturnValue(new Promise(() => {})) // keep this visit's counts after the run
      clipsTake(2)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('along')
      await waitFor(() => expect(h.api.lessons.get).toHaveBeenCalledTimes(2))
      expect(await screen.findByText(/Flow finished · 1 sentences · 1 skipped/)).toBeInTheDocument()
      expect(screen.getAllByRole('button', { name: 'Listen + me' })).toHaveLength(1)
      expect(usePractice.getState().storedTakes[11]).toBeUndefined()
      expect(usePractice.getState().storedTakes[12]).toMatchObject({ id: 99 })
      expect(usePractice.getState().lesson!.segments.map((s) => s.attempts)).toEqual([0, 1])
    })

    it('stopping midway submits the finished sentences, each to its own sentence, and drops the unfinished one', async () => {
      clipsTake(2, (n) => n === 2)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('along')
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(2))
      expect(screen.getByTestId('stage')).toHaveTextContent('Speak along')
      press('Enter')
      expect(await screen.findByText(/Flow finished · 1 sentences/)).toBeInTheDocument()
      await waitFor(() => expect(h.api.segments.postAttempt).toHaveBeenCalledTimes(1))
      expect(uploads()).toEqual([[11, 'flow']])
      expect(h.rec.stop).toHaveBeenCalledTimes(1)
    })

    it('skip (→) drops the current sentence and moves on', async () => {
      clipsTake(2, (n) => n === 1)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('along')
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(1))
      press('ArrowRight')
      expect(await screen.findByText(/Flow finished · 1 sentences · 1 skipped/)).toBeInTheDocument()
      await waitFor(() => expect(uploads()).toEqual([[12, 'flow']]))
    })

    it('switching mode mid-run stops gracefully: finished sentences are uploaded, the unfinished one dropped, then it switches', async () => {
      clipsTake(2, (n) => n === 2)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('along')
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(2))
      fireEvent.click(screen.getByRole('button', { name: 'Echo' }))
      await waitFor(() => expect(usePractice.getState().mode).toBe('echo'))
      await waitFor(() => expect(uploads()).toEqual([[11, 'flow']]))
      expect(h.rec.stop).toHaveBeenCalledTimes(1)
      await waitFor(() => expect(h.api.lessons.get).toHaveBeenCalledTimes(2)) // scores still refresh after the summary was closed
      await sleepMs(300)
      expect(h.player.play).toHaveBeenCalledTimes(2)
      expect(usePractice.getState().recordingNow).toBe(false)
      expect(screen.getByText('你好', { selector: 'p.sentence' })).toBeInTheDocument()
      expect(screen.queryByText(/Flow finished/)).toBeNull()
    })

    it('scores still refresh when the summary is closed while uploads are in flight', async () => {
      clipsTake(2)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      const upload = deferred<{ id: number }>()
      h.api.segments.postAttempt.mockReturnValue(upload.promise)
      await startFlow('along')
      expect(await screen.findByText(/Flow finished/)).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Done' }))
      await flush()
      expect(h.api.lessons.get).toHaveBeenCalledTimes(1)
      upload.resolve({ id: 1 })
      await waitFor(() => expect(h.api.lessons.get).toHaveBeenCalledTimes(2))
    })

    it('clicking the active Flow tab mid-run does nothing', async () => {
      clipsTake(2, () => true)
      await startFlow('after')
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(1))
      const stops = h.player.stop.mock.calls.length
      fireEvent.click(screen.getByRole('button', { name: 'Flow' }))
      await sleepMs(100)
      expect(screen.getByTestId('stage')).toHaveTextContent('Listening')
      expect(h.player.stop).toHaveBeenCalledTimes(stops)
      expect(h.rec.stop).not.toHaveBeenCalled()
      expect(h.api.segments.postAttempt).not.toHaveBeenCalled()
      expect(usePractice.getState().recordingNow).toBe(true)
    })

    it('after: the stage says your turn during the pause, with the record frame, live waveform and turn bar', async () => {
      clipsTake(2)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('after')
      await waitFor(() => expect(screen.getByTestId('stage')).toHaveTextContent('Your turn'))
      expect(screen.getByTestId('stage')).toHaveClass('border-record')
      expect(screen.getByTestId('live-wave')).toBeInTheDocument()
      expect(screen.getByTestId('turn-bar')).toBeInTheDocument()
      press('Enter')
      expect(await screen.findByText(/Flow finished/)).toBeInTheDocument()
      // the turn's frame loop ends with the run
      const raf = vi.spyOn(globalThis, 'requestAnimationFrame')
      try { await sleepMs(100); expect(raf).not.toHaveBeenCalled() } finally { raf.mockRestore() }
    })

    it('after with hide-text on: the sentence shows while listening and hides only during your turn', async () => {
      useSettings.setState({ practice: { ...useSettings.getState().practice, hideTextWhileRecording: true } })
      clipsTake(2, (n) => n === 1) // the first clip plays until released
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('after')
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(1))
      expect(screen.getByTestId('stage')).toHaveTextContent('Listening')
      expect(screen.getByTestId('stage')).toHaveTextContent('你好')
      act(() => { h.player.stop() }) // the clip ends: the turn opens
      await waitFor(() => expect(screen.getByTestId('stage')).toHaveTextContent('Your turn'))
      expect(screen.getByTestId('stage')).not.toHaveTextContent('你好')
      press('Enter')
      expect(await screen.findByText(/Flow finished/)).toBeInTheDocument()
    })

    it('along: the next sentence shows dimmed below the current one', async () => {
      clipsTake(2, () => true)
      await startFlow('along')
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(1))
      expect(screen.getByTestId('next-line')).toHaveTextContent('再见')
      expect(screen.getByTestId('live-wave')).toBeInTheDocument()
      expect(screen.queryByRole('meter')).toBeNull()
    })

    it('unmounting mid-run closes the mic and uploads nothing', async () => {
      clipsTake(2, () => true)
      await startFlow('after')
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(1))
      cleanup()
      await sleepMs(300)
      expect(h.rec.stop).toHaveBeenCalledTimes(1)
      expect(h.player.play).toHaveBeenCalledTimes(1)
      expect(h.api.segments.postAttempt).not.toHaveBeenCalled()
      expect(usePractice.getState().recordingNow).toBe(false)
    })

    it('the range defaults to the current passage', async () => {
      h.api.lessons.get.mockResolvedValue({ ...lesson, passages: [
        { idx: 0, title: 'P1', start_s: 0, end_s: 2, segment_ids: [11], done: false },
        { idx: 1, title: 'P2', start_s: 2, end_s: 4, segment_ids: [12], done: false }] })
      clipsTake(2)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('along')
      expect(await screen.findByText(/Flow finished · 1 sentences/)).toBeInTheDocument()
      expect(h.player.play.mock.calls.map((c) => (c as unknown[])[0])).toEqual(['/seg/11.opus'])
    })

    it('the last sentence of a run that ends before the lesson does previews no next line', async () => {
      h.api.lessons.get.mockResolvedValue({ ...lesson, passages: [
        { idx: 0, title: 'P1', start_s: 0, end_s: 2, segment_ids: [11], done: false },
        { idx: 1, title: 'P2', start_s: 2, end_s: 4, segment_ids: [12], done: false }] })
      clipsTake(2, () => true)
      await startFlow('along')
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(1))
      expect(screen.getByTestId('stage')).toHaveTextContent('Speak along')
      expect(screen.queryByTestId('next-line')).toBeNull()
    })

    it('starting a run clears a stale hint', async () => {
      clipsTake(2, () => true)
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      act(() => usePractice.getState().setHint('Sent to Anki'))
      await enterFlow()
      fireEvent.click(screen.getByRole('button', { name: 'after' }))
      expect(screen.getByText('Sent to Anki')).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Start flow (Enter)' }))
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(1))
      expect(screen.queryByText('Sent to Anki')).toBeNull()
    })

    it('a denied microphone returns to the setup with a readable error', async () => {
      h.rec.start.mockRejectedValue(new Error('Microphone permission was denied'))
      await startFlow('along')
      expect(await screen.findByRole('alert')).toHaveTextContent('Microphone permission was denied')
      expect(screen.getByRole('button', { name: 'Start flow (Enter)' })).toBeInTheDocument()
      expect(h.player.play).not.toHaveBeenCalled()
      expect(usePractice.getState().recordingNow).toBe(false)
    })

    it("closing the summary offers the run's sentences before the setup comes back", async () => {
      useSettings.setState({ exportNote: { deckName: 'D', modelName: 'M', fields: { sentence: 'S', audio: 'A' } } })
      clipsTake(2)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('along')
      await screen.findByText(/Flow finished · 2 sentences/)
      await waitFor(() => expect(usePractice.getState().practised).toEqual([11, 12]))
      fireEvent.click(screen.getByRole('button', { name: 'Done' }))
      const dialog = await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      expect(within(dialog).getAllByRole('checkbox')).toHaveLength(2)
      fireEvent.click(within(dialog).getByRole('button', { name: 'Close (Esc)' }))
      expect(await screen.findByRole('button', { name: 'Start flow (Enter)' })).toBeInTheDocument()
      cleanup(); useSettings.setState({ exportNote: null }) // unmount first: a store update reaching the mounted page warns about act()
    })

    const storedRun: FlowRun = { started_at: '2026-10-07T09:00:00Z', ended_at: '2026-10-07T09:01:00Z', session_id: 3,
      items: [{ segment_id: 11, idx: 0, attempt_id: 50, duration_s: 2 }, { segment_id: 12, idx: 1, attempt_id: 51, duration_s: 2 }] }

    it("entering Flow lists the last run; replay plays each sentence's original then its take, and any key stops it", async () => {
      h.api.lessons.flowRuns.mockResolvedValue([storedRun])
      // Take 51's voice is at 0.5..1.5 s; take 50 has none to go by and plays whole.
      const p51 = Float32Array.from({ length: 400 }, (_, i) => (i >= 100 && i < 300 ? 0.4 : 0))
      h.player.peaksFor.mockImplementation((url: string) => Promise.resolve(url === '/att/51.wav' ? p51 : new Float32Array(400)))
      let signal: AbortSignal | undefined
      h.playSequence.mockImplementation(((_p: unknown, _items: unknown, _gap: unknown, s: AbortSignal) => { signal = s; return new Promise(() => {}) }) as unknown as () => Promise<void>)
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      expect(h.api.lessons.flowRuns).not.toHaveBeenCalled()
      await enterFlow()
      expect(await screen.findByTestId('last-run')).toHaveTextContent('Last run')
      expect(h.api.lessons.flowRuns).toHaveBeenCalledWith(1)
      fireEvent.click(screen.getByRole('button', { name: 'Replay run' })); await flush()
      const [, items] = h.playSequence.mock.calls.at(-1) as unknown as [unknown, { url: string; rate: number }[]]
      const b = speechBounds(p51, 2)!
      expect(items).toEqual([{ url: '/seg/11.opus', rate: 1 }, { url: '/att/50.wav', rate: 1 }, { url: '/seg/12.opus', rate: 1 }, { url: '/att/51.wav', rate: 1, from: b.from, to: b.to }])
      expect(signal!.aborted).toBe(false)
      press(' '); await flush()
      expect(signal!.aborted).toBe(true)
    })

    it('the runs list refreshes once a run has uploaded', async () => {
      clipsTake(2)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('along')
      await screen.findByText(/Flow finished · 2 sentences/)
      await waitFor(() => expect(h.api.lessons.flowRuns).toHaveBeenCalledTimes(2))
      expect(usePractice.getState().storedTakes[12]).toMatchObject({ id: 99, url: '/att/99.wav' })
    })
  })

  describe('lesson list drawer', () => {
    const pos = () => screen.getByRole('button', { name: /^Lesson list/ })
    const list = () => screen.queryByTestId('lesson-drawer')
    it('is closed on load, even if the store said open; the position is a button with aria-expanded', async () => {
      usePractice.setState({ drawerOpen: true })
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      expect(list()).toBeNull()
      expect(pos()).toHaveAttribute('aria-expanded', 'false')
      expect(pos()).toHaveAttribute('title', 'Lesson list (L)')
      expect(pos()).toHaveTextContent('1 / 2')
    })
    it('the position opens it and again closes it; L, Esc, the scrim and × close it', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      const open = () => { fireEvent.click(pos()); expect(list()).not.toBeNull(); expect(pos()).toHaveAttribute('aria-expanded', 'true') }
      open(); fireEvent.click(pos()); expect(list()).toBeNull()
      open(); press('l'); expect(list()).toBeNull()
      open(); fireEvent.keyDown(document.body, { key: 'Escape' }); expect(list()).toBeNull()
      open(); fireEvent.click(screen.getByTestId('drawer-scrim')); expect(list()).toBeNull()
      open(); fireEvent.click(screen.getByRole('button', { name: 'Close lesson list (L)' })); expect(list()).toBeNull()
      expect(usePractice.getState().drawerOpen).toBe(false)
      expect(pos()).toHaveAttribute('aria-expanded', 'false')
    })
    it('one Esc closes only the help overlay, the next closes the drawer', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      fireEvent.click(pos())
      press('?')
      const help = await screen.findByRole('dialog', { name: 'How to practise' })
      fireEvent.keyDown(help, { key: 'Escape' })
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
      expect(list()).not.toBeNull()
      fireEvent.keyDown(document.body, { key: 'Escape' })
      expect(list()).toBeNull()
    })
    it('one Esc closes only the Sound pop-up, the next closes the drawer', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      fireEvent.click(pos())
      fireEvent.click(screen.getByRole('button', { name: 'Sound' }))
      expect(screen.getByLabelText('Playback speed')).toBeInTheDocument()
      fireEvent.keyDown(document.body, { key: 'Escape' })
      expect(screen.queryByLabelText('Playback speed')).toBeNull()
      expect(list()).not.toBeNull()
      fireEvent.keyDown(document.body, { key: 'Escape' })
      expect(list()).toBeNull()
    })
    it('with the drawer opened after the Sound pop-up, the first Esc closes only the pop-up', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      fireEvent.click(screen.getByRole('button', { name: 'Sound' }))
      expect(screen.getByLabelText('Playback speed')).toBeInTheDocument()
      fireEvent.click(pos())
      expect(list()).not.toBeNull()
      fireEvent.keyDown(document.body, { key: 'Escape' })
      expect(screen.queryByLabelText('Playback speed')).toBeNull()
      expect(list()).not.toBeNull()
      fireEvent.keyDown(document.body, { key: 'Escape' })
      expect(list()).toBeNull()
    })
    it('picking a sentence jumps to it and closes the drawer', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      fireEvent.click(pos())
      fireEvent.click(within(screen.getByTestId('lesson-drawer')).getAllByRole('button', { name: /再见/ })[0])
      expect(usePractice.getState().idx).toBe(1)
      expect(list()).toBeNull()
    })
    it('is not a dialog: Space still plays and arrows still move while it is open', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      fireEvent.click(pos())
      expect(screen.queryByRole('dialog')).toBeNull()
      press(' ')
      expect(h.player.play).toHaveBeenCalled()
      press('ArrowRight')
      expect(usePractice.getState().idx).toBe(1)
      expect(list()).not.toBeNull()
    })
    it('the edit dialog opens from a row menu (the drawer steps aside)', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      fireEvent.click(pos())
      fireEvent.click(screen.getByRole('button', { name: 'Actions for sentence 1' }))
      fireEvent.click(screen.getByRole('menuitem', { name: 'Edit text' }))
      expect(screen.getByRole('dialog')).toBeInTheDocument()
      expect(list()).toBeNull()
    })
  })

  describe('drawer actions', () => {
    const openMenu = (row: number, item: string) => {
      if (!screen.queryByRole('button', { name: `Actions for sentence ${row}` })) fireEvent.click(screen.getByRole('button', { name: /^Lesson list/ }))
      fireEvent.click(screen.getByRole('button', { name: `Actions for sentence ${row}` }))
      fireEvent.click(screen.getByRole('menuitem', { name: item }))
    }
    const reloadWith = (segments: Segment[]) => h.api.lessons.get.mockResolvedValueOnce(lesson).mockResolvedValueOnce({ ...lesson, segments })

    it('Edit text acts on the clicked row, not the current sentence, then reloads and stays on the current sentence', async () => {
      reloadWith([seg(11, 0, '你好'), seg(12, 1, '再见了')])
      h.api.segments.patch.mockResolvedValue(seg(12, 1, '再见了'))
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      openMenu(2, 'Edit text')
      const dialog = screen.getByRole('dialog')
      expect(dialog).toHaveAttribute('aria-modal', 'true')
      fireEvent.change(screen.getByRole('textbox'), { target: { value: '再见了' } })
      fireEvent.click(screen.getByRole('button', { name: 'Save and re-align' }))
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
      expect(h.api.segments.patch).toHaveBeenCalledWith(12, { text: '再见了' })
      expect(h.api.segments.clipChanged).toHaveBeenCalledWith(12)
      expect(h.api.lessons.get).toHaveBeenCalledTimes(2)
      expect(usePractice.getState().idx).toBe(0)
      expect(usePractice.getState().lesson!.segments[1].text).toBe('再见了')
      expect(h.api.lessons.takes).toHaveBeenCalledTimes(2) // the stored takes follow the reloaded sentences
    })

    it('an edit in the Flow setup reloads the stored runs, so a replay never names a merged-away sentence', async () => {
      reloadWith([seg(11, 0, '你好'), seg(12, 1, '再见了')])
      h.api.segments.patch.mockResolvedValue(seg(12, 1, '再见了'))
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      await enterFlow()
      expect(h.api.lessons.flowRuns).toHaveBeenCalledTimes(1)
      openMenu(2, 'Edit text')
      fireEvent.change(screen.getByRole('textbox'), { target: { value: '再见了' } })
      fireEvent.click(screen.getByRole('button', { name: 'Save and re-align' }))
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
      await waitFor(() => expect(h.api.lessons.flowRuns).toHaveBeenCalledTimes(2))
    })

    it('a rejected edit keeps the dialog open with the backend message', async () => {
      h.api.segments.patch.mockRejectedValue(new ApiError(400, 'Bad Request', '{"detail":"text needs at least one speech character"}', 'text needs at least one speech character'))
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      openMenu(1, 'Edit text')
      fireEvent.change(screen.getByRole('textbox'), { target: { value: '。' } })
      fireEvent.click(screen.getByRole('button', { name: 'Save and re-align' }))
      expect(await within(screen.getByRole('dialog')).findByRole('alert')).toHaveTextContent('Could not save the edit: text needs at least one speech character')
      expect(h.api.lessons.get).toHaveBeenCalledTimes(1)
    })

    it('global shortcuts do nothing while the dialog is open, including keys on its buttons', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      openMenu(1, 'Split here')
      const dialog = screen.getByRole('dialog')
      fireEvent.keyDown(within(dialog).getByRole('button', { name: '好' }), { key: ' ' })
      fireEvent.keyDown(within(dialog).getByRole('button', { name: 'Cancel' }), { key: 'ArrowRight' })
      press('l'); press('ArrowRight'); press(' ')
      expect(h.player.play).not.toHaveBeenCalled()
      expect(usePractice.getState()).toMatchObject({ idx: 0, drawerOpen: false })
      fireEvent.keyDown(dialog, { key: 'Escape' })
      expect(screen.queryByRole('dialog')).toBeNull()
      press('ArrowRight')
      expect(usePractice.getState().idx).toBe(1)
    })

    it('Split here resplits the clicked row at the chosen character and reloads', async () => {
      reloadWith([seg(11, 0, '你'), seg(13, 1, '好'), seg(12, 2, '再见')])
      h.api.segments.resplit.mockResolvedValue([seg(11, 0, '你'), seg(13, 1, '好')])
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      act(() => usePractice.getState().setIdx(1))
      openMenu(1, 'Split here')
      expect(within(screen.getByRole('dialog')).getByRole('button', { name: '你' })).toBeDisabled()
      fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: '好' }))
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
      expect(h.api.segments.resplit).toHaveBeenCalledWith(11, 1)
      expect(h.api.segments.clipChanged.mock.calls.map((c) => c[0])).toEqual([11, 13])
      expect(usePractice.getState().idx).toBe(2) // still on 再见, now third
      expect(screen.getByText('再见', { selector: 'p.sentence' })).toBeInTheDocument()
    })

    it('Merge with next merges the clicked row; when the current sentence merged away it lands on the merged one', async () => {
      reloadWith([seg(11, 0, '你好再见')])
      h.api.segments.mergeNext.mockResolvedValue(seg(11, 0, '你好再见'))
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      act(() => usePractice.getState().setIdx(1))
      fireEvent.click(screen.getByRole('button', { name: /^Lesson list/ }))
      expect(screen.getByRole('button', { name: 'Actions for sentence 2' })).toBeInTheDocument()
      fireEvent.click(screen.getByRole('button', { name: 'Actions for sentence 2' }))
      expect(screen.getByRole('menuitem', { name: 'Merge with next' })).toBeDisabled() // the last row has no next
      openMenu(1, 'Merge with next')
      await waitFor(() => expect(usePractice.getState().lesson!.segments).toHaveLength(1))
      expect(h.api.segments.mergeNext).toHaveBeenCalledWith(11)
      expect(h.api.segments.clipChanged).toHaveBeenCalledWith(11)
      expect(usePractice.getState().idx).toBe(0)
      expect(screen.getByText('你好再见', { selector: 'p.sentence' })).toBeInTheDocument()
    })

    it('a merge refused while the lesson is rebuilt shows why', async () => {
      h.api.segments.mergeNext.mockRejectedValue(new ApiError(409, 'Conflict', '{"detail":"this lesson is being rebuilt — try again in a moment"}', 'this lesson is being rebuilt — try again in a moment'))
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      openMenu(1, 'Merge with next')
      expect(await screen.findByRole('alert')).toHaveTextContent('Could not merge: this lesson is being rebuilt — try again in a moment')
    })

    it('a merge without a next sentence shows a readable message', async () => {
      h.api.segments.mergeNext.mockRejectedValue(new ApiError(409, 'Conflict', '{"detail":"no next segment"}', 'no next segment'))
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      openMenu(1, 'Merge with next')
      expect(await screen.findByRole('alert')).toHaveTextContent('There is no next sentence to merge with.')
      expect(h.api.lessons.get).toHaveBeenCalledTimes(1)
    })
  })

  describe('Anki export', () => {
    const cfg = { deckName: 'Shadow', modelName: 'Mining', fields: { sentence: 'Sentence', audio: 'Audio' } }
    afterEach(() => { cleanup(); useSettings.setState({ exportNote: null }) })

    it('A without an export note type points to Settings and sends nothing', async () => {
      useSettings.setState({ exportNote: null })
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      press('a')
      expect(await screen.findByRole('alert')).toHaveTextContent('Configure the export note type in Settings')
      expect(h.exportAndRecord).not.toHaveBeenCalled()
    })

    it('A sends the current sentence, confirms and records the note; a second A asks first', async () => {
      useSettings.setState({ exportNote: cfg })
      h.exportAndRecord.mockImplementation(async (s: Segment) => ({ ...s, anki_note_id: 1 }))
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      press('a')
      expect(await screen.findByText('Sent to Anki')).toBeInTheDocument()
      expect(h.exportAndRecord).toHaveBeenCalledWith(expect.objectContaining({ id: 11 }), useSettings.getState().ankiUrl, cfg, expect.objectContaining({ id: 1, title: 'Lesson' }))
      expect(usePractice.getState().lesson!.segments[0].anki_note_id).toBe(1)
      const ask = vi.spyOn(window, 'confirm').mockReturnValue(false)
      press('a')
      expect(ask).toHaveBeenCalledWith('"你好" is already in Anki. Send it again?')
      await flush()
      expect(h.exportAndRecord).toHaveBeenCalledTimes(1)
      ask.mockRestore()
    })

    it('A on a sentence imported from Anki sends it only when confirmed', async () => {
      useSettings.setState({ exportNote: cfg })
      h.api.lessons.get.mockResolvedValue({ ...lesson, segments: [{ ...seg(11, 0, '你好'), anki_note_id: 5 }, seg(12, 1, '再见')] })
      h.exportAndRecord.mockImplementation(async (s: Segment) => s)
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      const ask = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
      press('a')
      await flush()
      expect(h.exportAndRecord).not.toHaveBeenCalled()
      press('a')
      expect(await screen.findByText('Sent to Anki')).toBeInTheDocument()
      expect(h.exportAndRecord).toHaveBeenCalledTimes(1)
      expect(ask).toHaveBeenCalledTimes(2)
      ask.mockRestore()
    })

    it('an AnkiConnect error is shown readably', async () => {
      useSettings.setState({ exportNote: cfg })
      h.exportAndRecord.mockRejectedValue(new Error('"你好" is already in Anki, not added again.'))
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      press('a')
      expect(await screen.findByRole('alert')).toHaveTextContent('Anki export failed: "你好" is already in Anki, not added again.')
    })

    it('the Flow summary sends the weakest sentences', async () => {
      useSettings.setState({ exportNote: cfg })
      h.exportAndRecord.mockImplementation(async (s: Segment) => ({ ...s, anki_note_id: s.id * 100 }))
      const scored = { ...lesson, segments: [{ ...seg(11, 0, '你好'), last_score: 0.5 }, { ...seg(12, 1, '再见'), last_score: 0.9 }] }
      h.api.lessons.get.mockResolvedValueOnce(lesson).mockResolvedValue(scored)
      h.player.play.mockImplementation(() => { h.clock.t += 2; return Promise.resolve() })
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      await enterFlow()
      fireEvent.click(screen.getByRole('button', { name: 'along' }))
      fireEvent.click(screen.getByRole('button', { name: 'Start flow (Enter)' }))
      const send = await screen.findByRole('button', { name: 'Send weakest 3 to Anki' })
      await waitFor(() => expect(send).toBeEnabled())
      fireEvent.click(send)
      expect(await screen.findByText('Sent 2 sentences to Anki')).toBeInTheDocument()
      expect(h.exportAndRecord.mock.calls.map((c) => (c[0] as Segment).id)).toEqual([11, 12])
      expect(usePractice.getState().lesson!.segments.map((x) => x.anki_note_id)).toEqual([1100, 1200])
    })
  })

  describe('passages', () => {
    const twoPassages: LessonDetail = { ...lesson, passages: [
      { idx: 0, title: 'Passage 1 · 00:00–00:02', start_s: 0, end_s: 2, segment_ids: [11], done: false },
      { idx: 1, title: 'Passage 2 · 00:02–00:04', start_s: 2, end_s: 4, segment_ids: [12], done: false }] }
    beforeEach(() => { h.api.lessons.get.mockResolvedValue(twoPassages) })

    it('the top bar shows the passage and jumps to another one', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      expect(screen.getByText(/Passage 1 \/ 2/)).toBeInTheDocument()
      fireEvent.change(screen.getByLabelText('Go to passage'), { target: { value: '1' } })
      expect(await screen.findByText('再见', { selector: 'p.sentence' })).toBeInTheDocument()
      expect(screen.getByText(/Passage 2 \/ 2/)).toBeInTheDocument()
    })
  })

  describe('volume', () => {
    it('shows the guide level only in Flow along', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      fireEvent.click(screen.getByRole('button', { name: 'Sound' }))
      expect(screen.getByLabelText('Speaker volume')).toBeInTheDocument()
      expect(screen.queryByLabelText('Guide level')).toBeNull()
      await enterFlow()
      await waitFor(() => expect(screen.queryByLabelText('Guide level')).toBeNull()) // Flow starts in after
      fireEvent.click(screen.getByRole('button', { name: 'along' }))
      expect(screen.getByLabelText('Guide level')).toBeInTheDocument()
    })

    it('the speaker volume is saved in settings and applied to the player', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      fireEvent.click(screen.getByRole('button', { name: 'Sound' }))
      fireEvent.change(screen.getByLabelText('Speaker volume'), { target: { value: '60' } })
      expect(useSettings.getState().referenceVolume).toBeCloseTo(0.6)
      await waitFor(() => expect(h.player.setVolume).toHaveBeenLastCalledWith(0.6))
    })
  })

  describe('control bar', () => {
    const BAR = ['Previous sentence (←)', 'Lesson list (L)', 'Next sentence (→)', 'Listen (Space)', 'Record (Enter)', 'Me (R)', 'Anki (A)', 'Sound']
    const bar = () => screen.getByTestId('transport')

    it('the bar has prev · position · next, Listen, Record, Me, Anki and Sound', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      for (const name of BAR) expect(within(bar()).getByRole('button', { name })).toBeInTheDocument()
      expect(within(bar()).getByTestId('position')).toHaveTextContent('1 / 2')
      fireEvent.click(within(bar()).getByRole('button', { name: 'Next sentence (→)' }))
      expect(await screen.findByText('再见', { selector: 'p.sentence' })).toBeInTheDocument()
      expect(within(bar()).getByTestId('position')).toHaveTextContent('2 / 2')
      expect(within(bar()).getByRole('button', { name: 'Next sentence (→)' })).toBeDisabled() // the last sentence: nowhere to go
      fireEvent.click(within(bar()).getByRole('button', { name: 'Listen (Space)' }))
      expect(h.player.play).toHaveBeenLastCalledWith('/seg/12.opus', 1, expect.any(Function))
      fireEvent.click(within(bar()).getByRole('button', { name: 'Previous sentence (←)' }))
      expect(await screen.findByText('你好', { selector: 'p.sentence' })).toBeInTheDocument()
      fireEvent.click(within(bar()).getByRole('button', { name: 'Record (Enter)' }))
      expect(await within(bar()).findByRole('button', { name: 'Stop (Enter)' })).toBeInTheDocument()
    })

    it('no Finish session, C, F, T, P, E or 0.75× buttons on the bar', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      expect(within(bar()).getAllByRole('button').map((b) => b.getAttribute('aria-label'))).toEqual(BAR)
      expect(screen.queryByRole('button', { name: /Finish session/ })).toBeNull()
      expect(screen.queryByRole('button', { name: /0\.75/ })).toBeNull()
      expect(screen.queryByLabelText('Playback speed')).toBeNull() // speed and volume live in the Sound pop-up
      expect(screen.queryByLabelText('Speaker volume')).toBeNull()
    })

    it('⚑ Difficult and 字/pīn/EN sit on the sentence card and work', async () => {
      h.api.segments.patch.mockImplementation(async (id: number, p: { difficulty_flag: boolean }) => ({ ...lesson.segments.find((s) => s.id === id)!, ...p }))
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      const card = screen.getByTestId('sentence-card')
      expect(within(card).getByText('你好', { selector: 'p.sentence' })).toBeInTheDocument()
      fireEvent.click(within(card).getByRole('button', { name: 'Difficult (F)' }))
      expect(h.api.segments.patch).toHaveBeenCalledWith(11, { difficulty_flag: true })
      await waitFor(() => expect(within(card).getByRole('button', { name: 'Difficult (F)' })).toHaveAttribute('aria-pressed', 'true'))
      fireEvent.click(within(card).getByRole('button', { name: 'EN English (E)' }))
      expect(usePractice.getState().textPrefs).toEqual({ hanzi: true, pinyin: true, translation: true })
      fireEvent.click(within(card).getByRole('button', { name: 'pīn pinyin (P)' }))
      fireEvent.click(within(card).getByRole('button', { name: '字 characters (T)' }))
      expect(usePractice.getState().textPrefs).toEqual({ hanzi: false, pinyin: false, translation: true })
      expect(useSettings.getState().textPrefs['1']).toEqual({ hanzi: false, pinyin: false, translation: true })
      expect(screen.queryByText('你好', { selector: 'p.sentence' })).toBeNull()
      expect(within(screen.getByTestId('sentence-card')).getByRole('button', { name: '字 characters (T)' })).toHaveAttribute('aria-pressed', 'false')
      press('t') // the key does the same
      expect(await screen.findByText('你好', { selector: 'p.sentence' })).toBeInTheDocument()
    })

    it('keys still work while the Sound pop-up is open', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      // Keys as a browser sends them with nothing focused: from the body, bubbling through document to window.
      const key = (k: string) => fireEvent.keyDown(document.body, { key: k })
      fireEvent.click(within(bar()).getByRole('button', { name: 'Sound' }))
      expect(screen.getByLabelText('Playback speed')).toBeInTheDocument()
      key(' ')
      expect(h.player.play).toHaveBeenCalledWith('/seg/11.opus', 1, expect.any(Function))
      await flush()
      key('ArrowRight')
      expect(await screen.findByText('再见', { selector: 'p.sentence' })).toBeInTheDocument()
      expect(screen.getByLabelText('Playback speed')).toBeInTheDocument() // still open
      key('Enter')
      expect(await within(bar()).findByRole('button', { name: 'Stop (Enter)' })).toBeInTheDocument()
      await flush()
      key('Escape')
      expect(screen.queryByLabelText('Playback speed')).toBeNull()
    })

    it('the S key and the 0.75× preset toggle 0.75 ↔ 1', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      expect(usePractice.getState().rate).toBe(1)
      press('s')
      expect(usePractice.getState().rate).toBe(0.75)
      fireEvent.click(within(bar()).getByRole('button', { name: 'Sound' }))
      expect(screen.getByLabelText('Playback speed')).toHaveValue('0.75')
      const preset = screen.getByRole('button', { name: '0.75× (S)' })
      expect(preset).toHaveAttribute('aria-pressed', 'true')
      fireEvent.click(preset)
      expect(usePractice.getState().rate).toBe(1)
      expect(screen.getByLabelText('Playback speed')).toHaveValue('1')
      fireEvent.click(screen.getByRole('button', { name: '0.75× (S)' }))
      expect(usePractice.getState().rate).toBe(0.75)
      press('s')
      expect(usePractice.getState().rate).toBe(1)
    })
  })

  it('opens the help on the first visit only; Esc closes it and ? opens it again', async () => {
    useSettings.setState({ helpSeen: false })
    renderPractice()
    expect(await screen.findByRole('dialog', { name: 'How to practise' })).toBeInTheDocument()
    expect(useSettings.getState().helpSeen).toBe(true)
    press('Enter')                                   // page shortcuts are off while it is open
    await flush()
    expect(h.rec.start).not.toHaveBeenCalled()
    press('Escape')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    press('?')
    expect(await screen.findByRole('dialog', { name: 'How to practise' })).toBeInTheDocument()
    press('?')
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
  })

  it('? and Esc close the help with the focus inside it; the shortcuts work again afterwards', async () => {
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    expect(screen.queryByRole('dialog')).toBeNull() // seen before: it does not open by itself
    fireEvent.click(screen.getByRole('button', { name: 'Help' }))
    let got = within(await screen.findByRole('dialog', { name: 'How to practise' })).getByRole('button', { name: 'Got it (Esc)' })
    expect(got).toHaveFocus()
    fireEvent.keyDown(got, { key: '?' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    press('?')
    got = within(await screen.findByRole('dialog', { name: 'How to practise' })).getByRole('button', { name: 'Got it (Esc)' })
    fireEvent.keyDown(got, { key: 'Escape' })
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull())
    press('l')
    expect(usePractice.getState().drawerOpen).toBe(true)
  })

  it('a key another handler has already taken (default prevented) is not a page shortcut', async () => {
    const taken = (e: KeyboardEvent) => { if (e.key === 'l') e.preventDefault() }
    window.addEventListener('keydown', taken)
    try {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      press('l')
      expect(usePractice.getState().drawerOpen).toBe(false)
    } finally { window.removeEventListener('keydown', taken) }
  })

  it('recording shows Your turn with a live waveform and no mic meter', async () => {
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    expect(screen.getByTestId('stage')).not.toHaveTextContent(/Ready|Enter/)          // no "Ready — Enter to start" line…
    expect(screen.getByRole('button', { name: 'Record (Enter)' })).toHaveClass('pulse-next') // …Record pulses instead
    expect(screen.getByRole('button', { name: 'Next sentence (→)' })).not.toHaveClass('pulse-next')
    expect(screen.getByTestId('stage')).not.toHaveClass('border-record')
    press('Enter')
    await waitFor(() => expect(screen.getByTestId('stage')).toHaveTextContent('Your turn'))
    expect(screen.getByTestId('stage')).toHaveClass('border-record')
    expect(screen.getByRole('button', { name: 'Stop (Enter)' })).not.toHaveClass('pulse-next')
    expect(screen.getByRole('button', { name: 'Next sentence (→)' })).not.toHaveClass('pulse-next')
    expect(screen.getByTestId('rec-dot')).toBeInTheDocument()
    expect(screen.getByTestId('rec-timer')).toHaveTextContent(/^0:0\d$/)
    expect(screen.getByTestId('stage')).toContainElement(screen.getByTestId('live-wave'))
    await waitFor(() => expect(screen.getAllByTestId('wave-bar').length).toBeGreaterThan(0)) // the mic is open: flat bars
    expect(screen.queryByRole('meter')).toBeNull()
    expect(screen.queryByLabelText(/starting in/)).toBeNull() // Echo: no countdown, straight to your turn
    press('Enter'); await flush()
    // done: no "Done — → …" line; › pulses (move on), Record no longer does
    await waitFor(() => expect(screen.getByRole('button', { name: 'Next sentence (→)' })).toHaveClass('pulse-next'))
    expect(screen.getByRole('button', { name: 'Record (Enter)' })).not.toHaveClass('pulse-next')
    expect(screen.getByTestId('stage')).not.toHaveTextContent(/Done|Enter/)
    expect(screen.queryByTestId('live-wave')).toBeNull()
    expect(screen.getByTestId('stage')).not.toHaveClass('border-record')
  })

  it('an error clears when the reference plays and when the sentence changes', async () => {
    h.api.segments.patch.mockRejectedValue(new Error('boom'))
    h.player.play.mockImplementation(() => new Promise(() => {})) // still playing
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('f')
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not flag: boom')
    press(' ')
    await waitFor(() => expect(screen.getByTestId('stage')).toHaveTextContent('Listening'))
    expect(screen.queryByRole('alert')).toBeNull()
    press('f')
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not flag: boom')
    press('ArrowRight')
    expect(await screen.findByText('再见', { selector: 'p.sentence' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('the reference playback draws the colour wipe on an aligned sentence; without alignment only the cue shows', async () => {
    h.player.play.mockImplementation(() => new Promise(() => {})) // still playing
    h.api.lessons.get.mockResolvedValue({ ...lesson, segments: [
      { ...seg(11, 0, '你好'), ref_alignment_json: [{ ch: '你', start: 0.2, end: 0.5, conf: 1 }, { ch: '好', start: 0.5, end: 1, conf: 1 }] }, seg(12, 1, '再见')] })
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    expect(screen.queryByTestId('wipe')).toBeNull()
    press(' ')
    await waitFor(() => expect(screen.getByTestId('stage')).toHaveTextContent('Listening'))
    expect(screen.getByTestId('wipe')).toHaveAttribute('aria-hidden', 'true')
    press('ArrowRight') // 再见 has no alignment
    expect(await screen.findByText('再见', { selector: 'p.sentence' })).toBeInTheDocument()
    press(' ')
    await waitFor(() => expect(screen.getByTestId('stage')).toHaveTextContent('Listening'))
    expect(screen.queryByTestId('wipe')).toBeNull()
  })

  describe('session-end export', () => {
    const cfg = { deckName: 'chinese-shadow-speech', modelName: 'Shadow Listening', fields: { sentence: 'Sentence', audio: 'Audio' } }
    const long: LessonDetail = { ...lesson, segments: [seg(11, 0, '我今天想学中文'), seg(12, 1, '再见')] }
    beforeEach(() => { useSettings.setState({ exportNote: cfg }); h.api.lessons.get.mockResolvedValue(long) })
    afterEach(() => { cleanup(); useSettings.setState({ exportNote: null }) })
    const renderWithLibrary = () => render(
      <MemoryRouter initialEntries={['/practice/1']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <Routes><Route path="/practice/:id" element={<Practice />} /><Route path="/library" element={<div>library page</div>} /></Routes>
      </MemoryRouter>)
    async function takeOne() {
      await screen.findByText('我今天想学中文', { selector: 'p.sentence' })
      press('Enter'); await flush(); press('Enter'); await flush()
      await waitFor(() => expect(usePractice.getState().practised).toEqual([11]))
    }

    it('the back link offers the practised sentences, sends them, then goes to the library', async () => {
      h.exportAndRecord.mockImplementation(async (s: Segment) => ({ ...s, anki_note_id: 5 }))
      renderWithLibrary()
      await takeOne()
      fireEvent.click(screen.getByTitle('Back to the library'))
      const dialog = await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      fireEvent.click(within(dialog).getByRole('button', { name: 'Send 1 to Anki' }))
      expect(await within(dialog).findByText('sent ✓')).toBeInTheDocument()
      expect(h.exportAndRecord).toHaveBeenCalledWith(expect.objectContaining({ id: 11 }), useSettings.getState().ankiUrl, cfg, expect.objectContaining({ id: 1 }))
      expect(usePractice.getState().lesson!.segments[0].anki_note_id).toBe(5)
      fireEvent.click(within(dialog).getByRole('button', { name: 'Close (Esc)' }))
      expect(await screen.findByText('library page')).toBeInTheDocument()
    })

    it('fillers start unticked', async () => {
      h.api.lessons.get.mockResolvedValue(lesson)                 // 你好: two characters
      renderWithLibrary()
      await screen.findByText('你好', { selector: 'p.sentence' })
      press('Enter'); await flush(); press('Enter'); await flush()
      await waitFor(() => expect(usePractice.getState().practised).toEqual([11]))
      fireEvent.click(screen.getByTitle('Back to the library'))
      const dialog = await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      expect(within(dialog).getByRole('checkbox', { name: /你好/ })).not.toBeChecked()
    })

    it('⌂ Library still offers the session export when something is unsent', async () => {
      renderWithLibrary()
      await takeOne()
      fireEvent.click(screen.getByTitle('Back to the library'))
      expect(await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })).toBeInTheDocument()
      expect(screen.queryByText('library page')).toBeNull()
      fireEvent.click(screen.getByRole('button', { name: 'Close (Esc)' }))
      expect(await screen.findByText('library page')).toBeInTheDocument()
    })

    it('while the dialog is open the page shortcuts are off, and Esc closes it', async () => {
      renderWithLibrary()
      await takeOne()
      press('Enter') // a new take, still recording: leaving drops it
      await waitFor(() => expect(usePractice.getState().recordingNow).toBe(true))
      fireEvent.click(screen.getByTitle('Back to the library'))
      await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      expect(usePractice.getState().recordingNow).toBe(false)
      const starts = h.rec.start.mock.calls.length
      press('Enter'); press(' '); await flush()
      expect(h.rec.start).toHaveBeenCalledTimes(starts)
      expect(h.player.play).not.toHaveBeenCalled()
      press('Escape')
      expect(await screen.findByText('library page')).toBeInTheDocument()
    })

    it('a modified or middle click on the back link is left to the browser (a new tab), with no dialog', async () => {
      renderWithLibrary()
      await takeOne()
      const back = screen.getByTitle('Back to the library')
      // Records whether the page took the click, then stops jsdom's own navigation (not implemented, it would log).
      const taken: boolean[] = []
      const after = (e: Event) => { taken.push(e.defaultPrevented); e.preventDefault() }
      window.addEventListener('click', after)
      try {
        for (const init of [{ ctrlKey: true }, { metaKey: true }, { shiftKey: true }, { altKey: true }, { button: 1 }]) fireEvent.click(back, init)
        await flush()
      } finally { window.removeEventListener('click', after) }
      expect(taken).toEqual([false, false, false, false, false])
      expect(screen.queryByRole('dialog')).toBeNull()
      expect(screen.queryByText('library page')).toBeNull()
    })

    it('the back link during a Flow run stops it gracefully, uploads the finished sentences, offers them, then leaves', async () => {
      clipsTake(2, (n) => n === 2)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      renderWithLibrary()
      await screen.findByText('我今天想学中文', { selector: 'p.sentence' })
      await waitFor(() => expect(usePractice.getState().sessionId).toBe(5))
      await enterFlow()
      fireEvent.click(screen.getByRole('button', { name: 'along' }))
      fireEvent.click(screen.getByRole('button', { name: 'Start flow (Enter)' }))
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(2))
      fireEvent.click(screen.getByTitle('Back to the library'))
      const dialog = await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      expect(uploads()).toEqual([[11, 'flow']])
      expect(within(dialog).getAllByRole('checkbox').map((c) => c.closest('label')!.textContent)).toEqual(['我今天想学中文'])
      expect(screen.queryByText('library page')).toBeNull()
      fireEvent.click(within(dialog).getByRole('button', { name: 'Close (Esc)' }))
      expect(await screen.findByText('library page')).toBeInTheDocument()
    })

    async function startFlowRun(hold: (n: number) => boolean) {
      clipsTake(2, hold)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      renderWithLibrary()
      await screen.findByText('我今天想学中文', { selector: 'p.sentence' })
      await waitFor(() => expect(usePractice.getState().sessionId).toBe(5))
      await enterFlow()
      fireEvent.click(screen.getByRole('button', { name: 'along' }))
      fireEvent.click(screen.getByRole('button', { name: 'Start flow (Enter)' }))
    }
    const rowsOf = (dialog: HTMLElement) => within(dialog).getAllByRole('checkbox').map((c) => [c.closest('label')!.textContent, (c as HTMLInputElement).checked])

    it("the back link during a Flow run offers the run's sentences at once, without waiting for their uploads", async () => {
      const upload = deferred<{ id: number }>()
      h.api.segments.postAttempt.mockReturnValue(upload.promise)
      await startFlowRun((n) => n === 2)
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(2))
      fireEvent.click(screen.getByTitle('Back to the library'))
      const dialog = await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      expect(rowsOf(dialog)).toEqual([['我今天想学中文', true]])
      const starts = h.rec.start.mock.calls.length
      press('Enter'); await flush() // the dialog holds the keys: no new run
      expect(h.rec.start).toHaveBeenCalledTimes(starts)
      await act(async () => { upload.resolve({ id: 1 }) })
      await flush()
      expect(screen.getByRole('dialog', { name: 'Send what you practised to Anki?' })).toBeInTheDocument()
      expect(rowsOf(dialog)).toEqual([['我今天想学中文', true]])
      expect(screen.queryByText('library page')).toBeNull()
      fireEvent.click(within(dialog).getByRole('button', { name: 'Close (Esc)' }))
      expect(await screen.findByText('library page')).toBeInTheDocument()
    })

    it("Done right after a run lists the run's sentences; a slow upload resolving later neither navigates nor stops a new run", async () => {
      const upload = deferred<{ id: number }>()
      h.api.segments.postAttempt.mockReturnValue(upload.promise)
      await startFlowRun((n) => n >= 3) // the first run ends by itself, the second one keeps playing
      await screen.findByText(/Flow finished · 2 sentences/)
      fireEvent.click(screen.getByRole('button', { name: 'Done' }))
      const dialog = await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      expect(rowsOf(dialog)).toEqual([['我今天想学中文', true], ['再见filler', false]])
      fireEvent.click(within(dialog).getByRole('button', { name: 'Close (Esc)' }))
      fireEvent.click(await screen.findByRole('button', { name: 'Start flow (Enter)' }))
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(3))
      const stops = h.rec.stop.mock.calls.length
      await act(async () => { upload.resolve({ id: 1 }) })
      await sleepMs(300)
      expect(usePractice.getState().recordingNow).toBe(true)
      expect(h.rec.stop).toHaveBeenCalledTimes(stops)
      expect(screen.getByTestId('stage')).toHaveTextContent('Speak along')
      expect(screen.queryByRole('dialog')).toBeNull()
      expect(screen.queryByText('library page')).toBeNull()
    })

    it("the back link right after a run lists the run's sentences while their uploads are still pending", async () => {
      h.api.segments.postAttempt.mockReturnValue(new Promise(() => {}))
      await startFlowRun(() => false)
      await screen.findByText(/Flow finished · 2 sentences/)
      fireEvent.click(screen.getByTitle('Back to the library'))
      const dialog = await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      expect(rowsOf(dialog)).toEqual([['我今天想学中文', true], ['再见filler', false]])
    })

    it('Close and Esc wait while a send is in flight, so a sentence is never sent twice', async () => {
      const d = deferred<Segment>()
      h.exportAndRecord.mockReturnValue(d.promise)
      renderWithLibrary()
      await takeOne()
      fireEvent.click(screen.getByTitle('Back to the library'))
      const dialog = await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      fireEvent.click(within(dialog).getByRole('button', { name: 'Send 1 to Anki' }))
      expect(await within(dialog).findByText('sending…')).toBeInTheDocument()
      expect(within(dialog).getByRole('button', { name: 'Close (Esc)' })).toBeDisabled()
      press('Escape'); await flush()
      expect(screen.getByRole('dialog', { name: 'Send what you practised to Anki?' })).toBeInTheDocument()
      expect(screen.queryByText('library page')).toBeNull()
      await act(async () => { d.resolve({ ...long.segments[0], anki_note_id: 5 }) })
      expect(await within(dialog).findByText('sent ✓')).toBeInTheDocument()
      press('Escape')
      expect(await screen.findByText('library page')).toBeInTheDocument()
      expect(h.exportAndRecord).toHaveBeenCalledTimes(1)
    })

    it('a sentence still being sent with A is not offered again', async () => {
      const d = deferred<Segment>()
      h.exportAndRecord.mockReturnValue(d.promise)
      renderWithLibrary()
      await takeOne()
      press('a'); await flush()
      expect(h.exportAndRecord).toHaveBeenCalledTimes(1)
      fireEvent.click(screen.getByTitle('Back to the library'))
      expect(await screen.findByText('library page')).toBeInTheDocument()
      expect(screen.queryByRole('dialog')).toBeNull()
      await act(async () => { d.resolve({ ...long.segments[0], anki_note_id: 5 }) })
      expect(h.exportAndRecord).toHaveBeenCalledTimes(1)
    })

    it('with nothing to send, the back link leaves at once', async () => {
      renderWithLibrary()
      await screen.findByText('我今天想学中文', { selector: 'p.sentence' })
      fireEvent.click(screen.getByTitle('Back to the library'))
      expect(await screen.findByText('library page')).toBeInTheDocument()
      expect(screen.queryByRole('dialog')).toBeNull()
    })
  })
})
