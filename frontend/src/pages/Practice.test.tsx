import { act, cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { FlowRun, LessonDetail, Segment, Take } from '../api/types'
import { usePractice } from '../store/practice'
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
  player: { play: vi.fn(() => Promise.resolve()), playRange: vi.fn(() => Promise.resolve()), stop: vi.fn(), setVolume: vi.fn(), preload: vi.fn(() => Promise.resolve()), peaksFor: vi.fn<(url: string) => Promise<Float32Array>>(() => new Promise(() => {})) },
  ctxClose: vi.fn(() => Promise.resolve()),
  twoTrack: null as null | { onPlaySyllable: (i: number) => void; youPeaks: Float32Array | null; youDuration: number; score?: unknown },
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
  peaks: () => new Float32Array(4),
}))
vi.mock('../components/TwoTrack', () => ({
  default: (p: NonNullable<typeof h.twoTrack>) => { h.twoTrack = p; return <div data-testid="two-track" /> },
}))

import { ApiError } from '../api/client'
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

function renderPractice() {
  return render(<MemoryRouter initialEntries={['/practice/1']} future={{ v7_startTransition: true, v7_relativeSplatPath: true }}><Routes><Route path="/practice/:id" element={<Practice />} /></Routes></MemoryRouter>)
}

describe('<Practice>', () => {

  it('Echo: the uploaded take\u2019s score reaches the You track and the sentence\u2019s last score', async () => {
    const score = { overall: 0.8, tone_overall: 0.8, segmental_overall: null, rate_ratio: 1, ref_contour: null, usr_contour: null, syllables: [], warnings: [] }
    h.api.segments.postAttempt.mockResolvedValue({ id: 99, score_json: score })
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    await waitFor(() => expect(usePractice.getState().sessionId).toBe(5))
    press('Enter'); await screen.findByRole('button', { name: '■ stop' }); await flush()
    press('Enter'); await flush()
    await waitFor(() => expect(h.twoTrack?.score).toEqual(score))
    expect(usePractice.getState().lesson!.segments[0]).toMatchObject({ last_score: 0.8, attempts: 1 })
  })

  it('a gated take explains itself in the hint line', async () => {
    const score = { overall: null, tone_overall: null, segmental_overall: null, rate_ratio: null, ref_contour: null, usr_contour: null, syllables: [], warnings: ['too_quiet'] }
    h.api.segments.postAttempt.mockResolvedValue({ id: 99, score_json: score })
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('Enter'); await screen.findByRole('button', { name: '■ stop' }); await flush()
    press('Enter'); await flush()
    expect(await screen.findByText('Too quiet — not scored. Move closer to the mic.')).toBeInTheDocument()
  })

  it('a take of other words shows what was heard in the hint line', async () => {
    const score = { overall: null, tone_overall: null, segmental_overall: null, rate_ratio: null, ref_contour: null, usr_contour: null, syllables: [], warnings: ['different_words'], heard_text: '我是学生' }
    h.api.segments.postAttempt.mockResolvedValue({ id: 99, score_json: score })
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('Enter'); await screen.findByRole('button', { name: '■ stop' }); await flush()
    press('Enter'); await flush()
    expect(await screen.findByText('Heard different words — not scored. Heard: 我是学生')).toBeInTheDocument()
  })

  const gated = { overall: null, tone_overall: null, segmental_overall: null, rate_ratio: null, ref_contour: null, usr_contour: null, syllables: [], warnings: ['too_quiet'] }
  const scored = { ...gated, overall: 0.8, tone_overall: 0.8, warnings: [] }
  const QUIET = 'Too quiet — not scored. Move closer to the mic.'

  it('a gated take that uploads after moving on does not explain itself under the next sentence', async () => {
    const pending = deferred<{ id: number; score_json: typeof gated }>()
    h.api.segments.postAttempt.mockReturnValue(pending.promise)
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('Enter'); await screen.findByRole('button', { name: '■ stop' }); await flush()
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

  it('stored takes bring their score back when the lesson is reopened', async () => {
    const score = { overall: 0.6, tone_overall: 0.6, segmental_overall: null, rate_ratio: 1, ref_contour: null, usr_contour: null, syllables: [], warnings: [] }
    h.api.lessons.takes.mockResolvedValue([{ segment_id: 11, attempt_id: 7, mode: 'echo', created_at: '', duration_s: 1, score_json: score }])
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    await waitFor(() => expect(h.twoTrack?.score).toEqual(score))
  })
  const origAudioContext = globalThis.AudioContext
  const origCreate = URL.createObjectURL, origRevoke = URL.revokeObjectURL
  beforeEach(() => {
    vi.clearAllMocks()
    usePractice.setState({ lesson: null, idx: 0, mode: 'echo', sessionId: null, drawerOpen: true, attemptsThisSegment: 0, lastAttempt: null, recordingNow: false, hint: '', storedTakes: {} })
    // helpSeen: the help would otherwise open on every render and switch the shortcuts off. The volumes are reset here,
    // not at the end of a test, so no store update reaches a page that is still mounted (act() warnings).
    useSettings.setState({ helpSeen: true, referenceVolume: 1, guideLevel: 0.5 })
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

  it('a take under 0.2 s is discarded: no upload, no attempt counted, back to idle', async () => {
    h.rec.stop.mockReturnValue(new Float32Array(4410)) // 0.1 s at 44.1 kHz
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('Enter'); await flush(); press('Enter'); await flush()
    expect(h.api.segments.postAttempt).not.toHaveBeenCalled()
    expect(h.playSequence).not.toHaveBeenCalled()
    expect(usePractice.getState()).toMatchObject({ attemptsThisSegment: 0, lastAttempt: null, recordingNow: false })
    expect(screen.getByRole('alert')).toHaveTextContent(/Too short/)
    expect(screen.getByRole('button', { name: '● Enter' })).toBeInTheDocument()
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
    expect(usePractice.getState().drawerOpen).toBe(true)
  })

  describe('stored takes', () => {
    const take = (segment_id: number, attempt_id: number, duration_s: number): Take => ({ segment_id, attempt_id, mode: 'flow', created_at: '2026-10-07T09:00:00Z', duration_s })
    const played = () => h.player.play.mock.calls.map((c) => (c as unknown[])[0])

    it("R replays the sentence's stored take when the lesson is opened again; the You track shows it, per sentence", async () => {
      h.api.lessons.takes.mockResolvedValue([take(11, 77, 1.5), take(12, 78, 2.5)])
      const p77 = new Float32Array([0.5])
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
    beforeEach(() => { h.api.lessons.get.mockResolvedValue(aligned) })

    it('plays the clip-relative span of the clicked syllable once', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      act(() => h.twoTrack!.onPlaySyllable(1))
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
      act(() => h.twoTrack!.onPlaySyllable(0)); await flush()
      act(() => h.twoTrack!.onPlaySyllable(0)); await flush()
      expect(h.player.playRange).toHaveBeenCalledTimes(2)
      press('Enter'); await flush()
      act(() => h.twoTrack!.onPlaySyllable(0)); await flush()
      expect(h.player.playRange).toHaveBeenCalledTimes(2)
    })
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

  describe('Chorus', () => {
    let passes = 5
    beforeEach(() => { passes = useSettings.getState().practice.chorusPasses; useSettings.setState((s) => ({ practice: { ...s.practice, chorusPasses: 2 } })) })
    afterEach(() => { cleanup(); useSettings.setState((s) => ({ practice: { ...s.practice, chorusPasses: passes } })) })

    it('plays the passes at the guide level of the reference volume and shows the headphones hint once', async () => {
      useSettings.setState({ referenceVolume: 0.8, guideLevel: 0.5 })
      const atPlay: number[] = []
      h.player.play.mockImplementation(() => { atPlay.push(h.player.setVolume.mock.lastCall![0] as number); h.clock.t += 2; return Promise.resolve() })
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      await waitFor(() => expect(h.player.setVolume).toHaveBeenLastCalledWith(0.8))
      press('c')
      await waitFor(() => expect(h.playSequence).toHaveBeenCalled())
      expect(atPlay.length).toBeGreaterThan(0)
      atPlay.forEach((v) => expect(v).toBeCloseTo(0.4))
      expect(screen.getByText('Use headphones — the mic would pick up the reference')).toBeInTheDocument()
      await waitFor(() => expect(h.player.setVolume).toHaveBeenLastCalledWith(0.8)) // the takes play at the reference volume
    })

    it('C plays N passes, records only the last pass to its end + 0.3 s, uploads it as chorus and plays it back', async () => {
      const recordingAtPlay: boolean[] = []
      h.player.play.mockImplementation(() => { recordingAtPlay.push(usePractice.getState().recordingNow); h.clock.t += 2; return Promise.resolve() })
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      await waitFor(() => expect(usePractice.getState().sessionId).toBe(5))
      press('c')
      await waitFor(() => expect(h.api.segments.postAttempt).toHaveBeenCalled(), { timeout: 2000 })
      expect(h.rec.start).toHaveBeenCalledTimes(1)
      expect(h.player.play.mock.calls.map((c) => (c as unknown[])[0])).toEqual(['/seg/11.opus', '/seg/11.opus'])
      expect(recordingAtPlay).toEqual([false, true]) // the red indicator only on the last pass
      // last pass from t = 2 s to its end at 4 s, plus 0.3 s, on the recording clock
      expect(wavLengths()).toEqual([[Math.floor(4 * 44100) - 2 * 44100, 44100]])
      expect(h.api.segments.postAttempt).toHaveBeenCalledWith(11, expect.any(Blob), { session_id: 5, mode: 'chorus' })
      const [, items] = h.playSequence.mock.calls[0] as unknown as [unknown, { url: string }[]]
      expect(items.map((i) => i.url)).toEqual(['/seg/11.opus', 'blob:take'])
      expect(usePractice.getState()).toMatchObject({ recordingNow: false, attemptsThisSegment: 1 })
    })

    it('Enter in Chorus mode starts it; Enter again during the passes cancels it with nothing saved', async () => {
      clipsTake(2, () => true)
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      fireEvent.click(screen.getByRole('button', { name: 'Chorus' }))
      press('Enter')
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(1))
      expect(screen.getByRole('button', { name: '■ stop' })).toBeInTheDocument()
      press('Enter')
      await flush()
      expect(h.rec.stop).toHaveBeenCalledTimes(1) // the open mic is released
      await sleepMs(400)
      expect(h.player.play).toHaveBeenCalledTimes(1)
      expect(h.api.segments.postAttempt).not.toHaveBeenCalled()
      expect(usePractice.getState().recordingNow).toBe(false)
      expect(screen.getByRole('button', { name: '● Chorus ×2' })).toBeInTheDocument()
    })

    it('a denied microphone shows the error and plays nothing', async () => {
      h.rec.start.mockRejectedValue(new Error('Microphone permission was denied'))
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      press('c')
      expect(await screen.findByRole('alert')).toHaveTextContent('Microphone permission was denied')
      expect(h.player.play).not.toHaveBeenCalled()
      expect(screen.getByRole('button', { name: '● Enter' })).toBeInTheDocument()
      expect(usePractice.getState().recordingNow).toBe(false)
    })
  })

  describe('Flow', () => {
    async function startFlow(sub: 'after' | 'along' = 'along') {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      await waitFor(() => expect(usePractice.getState().sessionId).toBe(5))
      await enterFlow()
      fireEvent.click(screen.getByRole('button', { name: sub }))
      fireEvent.click(screen.getByRole('button', { name: 'Start' }))
    }

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
      await waitFor(() => expect(h.api.segments.postAttempt).toHaveBeenCalledTimes(2))
      expect(h.rec.start).toHaveBeenCalledTimes(1)
      expect(h.player.play.mock.calls.map((c) => (c as unknown[])[0])).toEqual(['/seg/11.opus', '/seg/12.opus'])
      expect(uploads()).toEqual([[11, 'flow'], [12, 'flow']])
      expect(h.api.segments.postAttempt).toHaveBeenCalledWith(11, expect.any(Blob), { session_id: 5, mode: 'flow' })
      // clip 1 played 0–2 s, clip 2 2–4 s; each slice spans its clip with 150 ms slack
      expect(wavLengths()).toEqual([[Math.floor(2.15 * 44100), 44100], [Math.floor(4.15 * 44100) - Math.floor(1.85 * 44100), 44100]])
      await waitFor(() => expect(h.api.lessons.get).toHaveBeenCalledTimes(2)) // scores refreshed
      expect(usePractice.getState().recordingNow).toBe(false)
      fireEvent.click(screen.getAllByRole('button', { name: '▶ ref+you' })[1])
      const [, items] = h.playSequence.mock.calls.at(-1) as unknown as [unknown, { url: string; rate: number }[]]
      expect(items).toEqual([{ url: '/seg/12.opus', rate: 1 }, { url: 'blob:take', rate: 1 }])
    })

    it('stopping midway submits the finished sentences, each to its own sentence, and drops the unfinished one', async () => {
      clipsTake(2, (n) => n === 2)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('along')
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(2))
      expect(screen.getByTestId('cue-line')).toHaveTextContent('Speak along')
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
      fireEvent.click(screen.getByRole('button', { name: 'done' }))
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
      expect(screen.getByTestId('cue-line')).toHaveTextContent('Listen')
      expect(h.player.stop).toHaveBeenCalledTimes(stops)
      expect(h.rec.stop).not.toHaveBeenCalled()
      expect(h.api.segments.postAttempt).not.toHaveBeenCalled()
      expect(usePractice.getState().recordingNow).toBe(true)
    })

    it('after: the cue line says your turn during the pause, with the turn bar', async () => {
      clipsTake(2)
      h.rec.stop.mockReturnValue(new Float32Array(44100 * 10))
      await startFlow('after')
      await waitFor(() => expect(screen.getByTestId('cue-line')).toHaveTextContent('Your turn — speak now'))
      expect(screen.getByTestId('turn-bar')).toBeInTheDocument()
      press('Enter')
      expect(await screen.findByText(/Flow finished/)).toBeInTheDocument()
      // the turn's frame loop ends with the run
      const raf = vi.spyOn(globalThis, 'requestAnimationFrame')
      try { await sleepMs(100); expect(raf).not.toHaveBeenCalled() } finally { raf.mockRestore() }
    })

    it('along: the next sentence shows dimmed below the current one', async () => {
      clipsTake(2, () => true)
      await startFlow('along')
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(1))
      expect(screen.getByTestId('next-line')).toHaveTextContent('再见')
      expect(screen.getByRole('meter', { name: 'Microphone level' })).toBeInTheDocument()
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
      expect(screen.getByTestId('cue-line')).toHaveTextContent('Speak along')
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
      fireEvent.click(screen.getByRole('button', { name: 'Start' }))
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(1))
      expect(screen.queryByText('Sent to Anki')).toBeNull()
    })

    it('a denied microphone returns to the setup with a readable error', async () => {
      h.rec.start.mockRejectedValue(new Error('Microphone permission was denied'))
      await startFlow('along')
      expect(await screen.findByRole('alert')).toHaveTextContent('Microphone permission was denied')
      expect(screen.getByRole('button', { name: '● Start flow' })).toBeInTheDocument()
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
      fireEvent.click(screen.getByRole('button', { name: 'done' }))
      const dialog = await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      expect(within(dialog).getAllByRole('checkbox')).toHaveLength(2)
      fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
      expect(await screen.findByRole('button', { name: 'Start' })).toBeInTheDocument()
      cleanup(); useSettings.setState({ exportNote: null }) // unmount first: a store update reaching the mounted page warns about act()
    })

    const storedRun: FlowRun = { started_at: '2026-10-07T09:00:00Z', ended_at: '2026-10-07T09:01:00Z', session_id: 3,
      items: [{ segment_id: 11, idx: 0, attempt_id: 50 }, { segment_id: 12, idx: 1, attempt_id: 51 }] }

    it("entering Flow lists the last run; replay plays each sentence's original then its take, and any key stops it", async () => {
      h.api.lessons.flowRuns.mockResolvedValue([storedRun])
      let signal: AbortSignal | undefined
      h.playSequence.mockImplementation(((_p: unknown, _items: unknown, _gap: unknown, s: AbortSignal) => { signal = s; return new Promise(() => {}) }) as unknown as () => Promise<void>)
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      expect(h.api.lessons.flowRuns).not.toHaveBeenCalled()
      await enterFlow()
      expect(await screen.findByTestId('last-run')).toHaveTextContent('Last run')
      expect(h.api.lessons.flowRuns).toHaveBeenCalledWith(1)
      fireEvent.click(screen.getByRole('button', { name: '▶ replay' }))
      const [, items] = h.playSequence.mock.calls.at(-1) as unknown as [unknown, { url: string; rate: number }[]]
      expect(items).toEqual([{ url: '/seg/11.opus', rate: 1 }, { url: '/att/50.wav', rate: 1 }, { url: '/seg/12.opus', rate: 1 }, { url: '/att/51.wav', rate: 1 }])
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

  it('Guided: listen → whisper (text shown, no mic) → record (text hidden), uploads as guided, then advances', async () => {
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    fireEvent.click(screen.getByRole('button', { name: 'Guided' }))
    press('Enter')
    expect(await screen.findByRole('button', { name: '● Whisper along (text visible)' })).toBeInTheDocument()
    expect(screen.getByText('你好', { selector: 'p.sentence' })).toBeInTheDocument()
    press('Enter')
    expect(await screen.findByRole('button', { name: '● Now record, text hidden' })).toBeInTheDocument()
    expect(h.player.play).toHaveBeenCalledTimes(2)
    expect(h.rec.start).not.toHaveBeenCalled() // the whisper pass is not recorded
    expect(screen.queryByText('你好', { selector: 'p.sentence' })).toBeNull()
    press('Enter')
    expect(await screen.findByRole('button', { name: '■ stop' })).toBeInTheDocument()
    await flush()
    press('Enter')
    await flush()
    expect(uploads()).toEqual([[11, 'guided']])
    await waitFor(() => expect(usePractice.getState().idx).toBe(1))
    expect(await screen.findByRole('button', { name: '● Listen once' })).toBeInTheDocument()
    expect(screen.getByText('再见', { selector: 'p.sentence' })).toBeInTheDocument()
  })

  it('Guided: the cue line names each step, and the record step says it is your turn', async () => {
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    fireEvent.click(screen.getByRole('button', { name: 'Guided' }))
    const cue = () => screen.getByTestId('cue-line')
    expect(cue()).toHaveTextContent('Ready — Enter to listen')
    press('Enter')
    await waitFor(() => expect(cue()).toHaveTextContent('Ready — Enter, then whisper along'))
    press('Enter')
    await waitFor(() => expect(cue()).toHaveTextContent('Ready — Enter, then say it without the text'))
    press('Enter')
    await waitFor(() => expect(cue()).toHaveTextContent('Your turn — say it without the text'))
    expect(await screen.findByRole('meter', { name: 'Microphone level' })).toBeInTheDocument()
  })

  describe('drawer actions', () => {
    const openMenu = (row: number, item: string) => {
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
      expect(usePractice.getState()).toMatchObject({ idx: 0, drawerOpen: true })
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
      fireEvent.click(screen.getByRole('button', { name: 'Start' }))
      const send = await screen.findByRole('button', { name: 'A → Anki weakest 3' })
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
    it('shows the guide level only in Chorus and Flow along', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      expect(screen.getByLabelText('Reference volume')).toBeInTheDocument()
      expect(screen.queryByLabelText('Guide level')).toBeNull()
      fireEvent.click(screen.getByRole('button', { name: 'Chorus' }))
      expect(await screen.findByLabelText('Guide level')).toBeInTheDocument()
      await enterFlow()
      await waitFor(() => expect(screen.queryByLabelText('Guide level')).toBeNull()) // Flow starts in after
      fireEvent.click(screen.getByRole('button', { name: 'along' }))
      expect(screen.getByLabelText('Guide level')).toBeInTheDocument()
    })

    it('shows the guide level while a Chorus started with C from Echo runs', async () => {
      clipsTake(2, () => true)
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      expect(screen.queryByLabelText('Guide level')).toBeNull()
      press('c')
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(1))
      expect(screen.getByLabelText('Guide level')).toBeInTheDocument()
      press('c') // stops it
      await waitFor(() => expect(screen.queryByLabelText('Guide level')).toBeNull())
    })

    it('the reference volume is saved in settings and applied to the player', async () => {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      fireEvent.change(screen.getByLabelText('Reference volume'), { target: { value: '60' } })
      expect(useSettings.getState().referenceVolume).toBeCloseTo(0.6)
      await waitFor(() => expect(h.player.setVolume).toHaveBeenLastCalledWith(0.6))
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
    expect(usePractice.getState().drawerOpen).toBe(false)
  })

  it('a key another handler has already taken (default prevented) is not a page shortcut', async () => {
    const taken = (e: KeyboardEvent) => { if (e.key === 'l') e.preventDefault() }
    window.addEventListener('keydown', taken)
    try {
      renderPractice()
      await screen.findByText('你好', { selector: 'p.sentence' })
      press('l')
      expect(usePractice.getState().drawerOpen).toBe(true)
    } finally { window.removeEventListener('keydown', taken) }
  })

  it('the cue line says what to do: ready, your turn with a moving mic meter, then done', async () => {
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    expect(screen.getByTestId('cue-line')).toHaveTextContent('Ready — Enter to start')
    press('Enter')
    await waitFor(() => expect(screen.getByTestId('cue-line')).toHaveTextContent('Your turn — speak now'))
    expect(await screen.findByRole('meter', { name: 'Microphone level' })).toBeInTheDocument()
    press('Enter'); await flush()
    await waitFor(() => expect(screen.getByTestId('cue-line')).toHaveTextContent('Done — → for the next sentence, Enter to try again'))
    await waitFor(() => expect(screen.queryByRole('meter', { name: 'Microphone level' })).toBeNull()) // next 50 ms poll
  })

  it('an error clears when the reference plays and when the sentence changes', async () => {
    h.api.segments.patch.mockRejectedValue(new Error('boom'))
    h.player.play.mockImplementation(() => new Promise(() => {})) // still playing
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    press('f')
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not flag: boom')
    expect(screen.getByTestId('cue-line')).toHaveTextContent('Something went wrong')
    press(' ')
    await waitFor(() => expect(screen.getByTestId('cue-line')).toHaveTextContent('Listen'))
    expect(screen.queryByRole('alert')).toBeNull()
    press('f')
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not flag: boom')
    press('ArrowRight')
    expect(await screen.findByText('再见', { selector: 'p.sentence' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
    expect(screen.getByTestId('cue-line')).not.toHaveTextContent('Something went wrong')
  })

  it('the reference playback draws the colour wipe on an aligned sentence; without alignment only the cue shows', async () => {
    h.player.play.mockImplementation(() => new Promise(() => {})) // still playing
    h.api.lessons.get.mockResolvedValue({ ...lesson, segments: [
      { ...seg(11, 0, '你好'), ref_alignment_json: [{ ch: '你', start: 0.2, end: 0.5, conf: 1 }, { ch: '好', start: 0.5, end: 1, conf: 1 }] }, seg(12, 1, '再见')] })
    renderPractice()
    await screen.findByText('你好', { selector: 'p.sentence' })
    expect(screen.queryByTestId('wipe')).toBeNull()
    press(' ')
    await waitFor(() => expect(screen.getByTestId('cue-line')).toHaveTextContent('Listen'))
    expect(screen.getByTestId('wipe')).toHaveAttribute('aria-hidden', 'true')
    press('ArrowRight') // 再见 has no alignment
    expect(await screen.findByText('再见', { selector: 'p.sentence' })).toBeInTheDocument()
    press(' ')
    await waitFor(() => expect(screen.getByTestId('cue-line')).toHaveTextContent('Listen'))
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

    it('Finish session offers the practised sentences, sends them, then goes to the library', async () => {
      h.exportAndRecord.mockImplementation(async (s: Segment) => ({ ...s, anki_note_id: 5 }))
      renderWithLibrary()
      await takeOne()
      fireEvent.click(screen.getByRole('button', { name: 'Finish session' }))
      const dialog = await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      fireEvent.click(within(dialog).getByRole('button', { name: 'Send 1 to Anki' }))
      expect(await within(dialog).findByText('sent ✓')).toBeInTheDocument()
      expect(h.exportAndRecord).toHaveBeenCalledWith(expect.objectContaining({ id: 11 }), useSettings.getState().ankiUrl, cfg, expect.objectContaining({ id: 1 }))
      expect(usePractice.getState().lesson!.segments[0].anki_note_id).toBe(5)
      fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
      expect(await screen.findByText('library page')).toBeInTheDocument()
    })

    it('fillers start unticked', async () => {
      h.api.lessons.get.mockResolvedValue(lesson)                 // 你好: two characters
      renderWithLibrary()
      await screen.findByText('你好', { selector: 'p.sentence' })
      press('Enter'); await flush(); press('Enter'); await flush()
      await waitFor(() => expect(usePractice.getState().practised).toEqual([11]))
      fireEvent.click(screen.getByRole('button', { name: 'Finish session' }))
      const dialog = await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      expect(within(dialog).getByRole('checkbox', { name: /你好/ })).not.toBeChecked()
    })

    it('the back link asks first when something practised is not in Anki', async () => {
      renderWithLibrary()
      await takeOne()
      fireEvent.click(screen.getByTitle('Back to the library'))
      expect(await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })).toBeInTheDocument()
      expect(screen.queryByText('library page')).toBeNull()
      fireEvent.click(screen.getByRole('button', { name: 'Close' }))
      expect(await screen.findByText('library page')).toBeInTheDocument()
    })

    it('while the dialog is open the page shortcuts are off, and Esc closes it', async () => {
      renderWithLibrary()
      await takeOne()
      press('Enter') // a new take, still recording: Finish session drops it
      await waitFor(() => expect(usePractice.getState().recordingNow).toBe(true))
      fireEvent.click(screen.getByRole('button', { name: 'Finish session' }))
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
      fireEvent.click(screen.getByRole('button', { name: 'Start' }))
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(2))
      fireEvent.click(screen.getByTitle('Back to the library'))
      const dialog = await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      expect(uploads()).toEqual([[11, 'flow']])
      expect(within(dialog).getAllByRole('checkbox').map((c) => c.closest('label')!.textContent)).toEqual(['我今天想学中文'])
      expect(screen.queryByText('library page')).toBeNull()
      fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
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
      fireEvent.click(screen.getByRole('button', { name: 'Start' }))
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
      fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
      expect(await screen.findByText('library page')).toBeInTheDocument()
    })

    it("Done right after a run lists the run's sentences; a slow upload resolving later neither navigates nor stops a new run", async () => {
      const upload = deferred<{ id: number }>()
      h.api.segments.postAttempt.mockReturnValue(upload.promise)
      await startFlowRun((n) => n >= 3) // the first run ends by itself, the second one keeps playing
      await screen.findByText(/Flow finished · 2 sentences/)
      fireEvent.click(screen.getByRole('button', { name: 'done' }))
      const dialog = await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      expect(rowsOf(dialog)).toEqual([['我今天想学中文', true], ['再见filler', false]])
      fireEvent.click(within(dialog).getByRole('button', { name: 'Close' }))
      fireEvent.click(await screen.findByRole('button', { name: 'Start' }))
      await waitFor(() => expect(h.player.play).toHaveBeenCalledTimes(3))
      const stops = h.rec.stop.mock.calls.length
      await act(async () => { upload.resolve({ id: 1 }) })
      await sleepMs(300)
      expect(usePractice.getState().recordingNow).toBe(true)
      expect(h.rec.stop).toHaveBeenCalledTimes(stops)
      expect(screen.getByTestId('cue-line')).toHaveTextContent('Speak along')
      expect(screen.queryByRole('dialog')).toBeNull()
      expect(screen.queryByText('library page')).toBeNull()
    })

    it("Finish session right after a run lists the run's sentences while their uploads are still pending", async () => {
      h.api.segments.postAttempt.mockReturnValue(new Promise(() => {}))
      await startFlowRun(() => false)
      await screen.findByText(/Flow finished · 2 sentences/)
      fireEvent.click(screen.getByRole('button', { name: 'Finish session' }))
      const dialog = await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      expect(rowsOf(dialog)).toEqual([['我今天想学中文', true], ['再见filler', false]])
    })

    it('Close and Esc wait while a send is in flight, so a sentence is never sent twice', async () => {
      const d = deferred<Segment>()
      h.exportAndRecord.mockReturnValue(d.promise)
      renderWithLibrary()
      await takeOne()
      fireEvent.click(screen.getByRole('button', { name: 'Finish session' }))
      const dialog = await screen.findByRole('dialog', { name: 'Send what you practised to Anki?' })
      fireEvent.click(within(dialog).getByRole('button', { name: 'Send 1 to Anki' }))
      expect(await within(dialog).findByText('sending…')).toBeInTheDocument()
      expect(within(dialog).getByRole('button', { name: 'Close' })).toBeDisabled()
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
      fireEvent.click(screen.getByRole('button', { name: 'Finish session' }))
      expect(await screen.findByText('library page')).toBeInTheDocument()
      expect(screen.queryByRole('dialog')).toBeNull()
      await act(async () => { d.resolve({ ...long.segments[0], anki_note_id: 5 }) })
      expect(h.exportAndRecord).toHaveBeenCalledTimes(1)
    })

    it('with nothing to send, the back link and Finish session leave at once', async () => {
      renderWithLibrary()
      await screen.findByText('我今天想学中文', { selector: 'p.sentence' })
      fireEvent.click(screen.getByTitle('Back to the library'))
      expect(await screen.findByText('library page')).toBeInTheDocument()
      expect(screen.queryByRole('dialog')).toBeNull()
    })
  })
})
