import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DrillFocus, DrillItem, DrillRecent, DrillSession, DrillSummary, Score, Segment, SylStatus } from '../api/types'
import { ApiError } from '../api/client'
import Shell from '../components/Shell'
import { useSettings } from '../store/settings'

const h = vi.hoisted(() => ({
  drill: { focuses: vi.fn(), recent: vi.fn(), start: vi.fn(), end: vi.fn(), summary: vi.fn() },
  segments: { audioUrl: (id: number, fmt = 'opus') => `/seg/${id}.${fmt}`, postAttempt: vi.fn() },
  rec: { start: vi.fn(), stop: vi.fn(), sampleRate: 44100 },
  findSilenceEnd: vi.fn((): number | null => null), // the auto-stop's VAD: null = still speaking (or not yet)
  toWav16k: vi.fn(() => new Blob(['wav'])),
  playSequence: vi.fn(() => Promise.resolve()),
  takePeaks: new Float32Array(4), // what peaks() returns for a fresh take's You waveform
  player: { play: vi.fn(() => Promise.resolve()), playRange: vi.fn(() => Promise.resolve()), stop: vi.fn(), setVolume: vi.fn(), preload: vi.fn(() => Promise.resolve()), peaksFor: vi.fn(() => new Promise(() => {})) },
  twoTrack: null as null | { highlight?: number[]; score?: unknown; segment: { id: number }; youPeaks?: Float32Array | null },
}))
vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api/client')>()), api: { drill: h.drill, segments: h.segments } }))
vi.mock('../audio/recorder', () => ({
  Recorder: class {
    get sampleRate() { return h.rec.sampleRate }
    start() { return h.rec.start() }
    stop() { return h.rec.stop() }
    snapshot() { return new Float32Array(0) }
    get startTime() { return 0 }
    tail() { return new Float32Array(0) }
  },
  toWav16k: h.toWav16k,
}))
vi.mock('../audio/pcm', async (importOriginal) => ({ ...(await importOriginal<typeof import('../audio/pcm')>()), findSilenceEnd: h.findSilenceEnd }))
vi.mock('../audio/player', () => ({
  ClipPlayer: class { constructor() { return h.player } },
  playSequence: h.playSequence,
  peaks: () => h.takePeaks,
}))
vi.mock('../components/TwoTrack', () => ({
  default: (p: NonNullable<typeof h.twoTrack>) => { h.twoTrack = p; return <div data-testid="two-track" /> },
}))
import { speechBounds } from '../lib/speech'
import Drill from './Drill'

const focus = (kind: DrillFocus['kind'], key: string, label: string, mean: number, n: number): DrillFocus => ({ kind, key, label, mean, n })
const focuses = [
  focus('pair', '3-3', 'tone pair 3→3', 0.31, 24), focus('tone', '3', 'tone 3 (low)', 0.42, 120),
  focus('char', '在', '在 zài', 0.5, 12), focus('tone', '2', 'tone 2 (rising)', 0.6, 80),
]
const seg = (id: number, idx: number, text: string): Segment => ({
  id, lesson_id: 3, idx, start_s: 0, end_s: 2, text, translation: null, words_json: null, ref_alignment_json: null,
  difficulty_flag: false, anki_note_id: null, last_score: null, best_score: null, attempts: 0,
})
const item = (id: number, idx: number, text: string, targets: number[]): DrillItem => ({ segment: seg(id, idx, text), lesson_id: 3, lesson_title: 'Lesson A', targets })
const run = (items: DrillItem[], id = 7): DrillSession => ({ id, kind: 'tone', key: '3', label: 'tone 3 (low)', short: false, items })
const twoItems = [item(11, 0, '你好吗', [0, 1]), item(12, 1, '我很好', [0, 1, 2])]
const score = (statuses: SylStatus[], overall: number | null = 0.7, warnings: string[] = []): Score => ({
  overall, tone_overall: overall, segmental_overall: null, rate_ratio: 1, ref_contour: null, usr_contour: null, warnings,
  syllables: statuses.map((status) => ({ ch: 'x', pinyin: 'x', tone: 3, target_tone: 3, heard_tone: 3, status, tone_score: 0.5, p_target: 0.5, contour: 0.5 })),
})
const green = score(['ok', 'ok', 'ok'])
const notGreen = score(['ok', 'wrong', 'ok'])
const gated = score([], null, ['too_quiet'])
const summary: DrillSummary = {
  id: 7, kind: 'tone', key: '3', label: 'tone 3 (low)', first_mean: 0.55, best_mean: 0.72, green_first: 3, green_best: 4, n_targets: 5,
  items: [
    { segment_id: 11, lesson_id: 3, lesson_title: 'Lesson A', idx: 0, text: '你好吗', targets: [0, 1], tries: 1, first: { attempt_id: 1, mean: 0.9, green: 2 }, best: { attempt_id: 1, mean: 0.9, green: 2 }, went_green: true },
    { segment_id: 12, lesson_id: 3, lesson_title: 'Lesson A', idx: 1, text: '我很好', targets: [0, 1, 2], tries: 3, first: { attempt_id: 2, mean: 0.4, green: 1 }, best: { attempt_id: 4, mean: 0.6, green: 2 }, went_green: false },
  ],
  history: [{ session_id: 7, started_at: '2026-10-14T10:00:00', first_mean: 0.55, best_mean: 0.72 }],
}
const last: DrillRecent = { id: 5, kind: 'tone', key: '4', label: 'tone 4 (falling)', started_at: '', ended_at: '2026-10-13T10:00:00', first_mean: 0.52, best_mean: 0.71 }
const future = { v7_startTransition: true, v7_relativeSplatPath: true }
const renderAt = (url = '/drill') => render(<MemoryRouter future={future} initialEntries={[url]}><Drill /></MemoryRouter>)
const flush = () => act(async () => { for (let i = 0; i < 10; i++) await Promise.resolve() })
const press = (key: string) => fireEvent.keyDown(window, { key })
const QUIET = 'Too quiet — not scored. Move closer to the mic.'

const origAudioContext = globalThis.AudioContext
const origCreate = URL.createObjectURL, origRevoke = URL.revokeObjectURL
beforeEach(() => {
  vi.clearAllMocks()
  Object.values(h.drill).forEach((f) => f.mockReset())
  // Rotation: the weakest focus (3→3) was drilled last time, so `auto` is the next one.
  h.drill.focuses.mockResolvedValue({ focuses, auto: { kind: 'tone', key: '3' } })
  h.drill.recent.mockResolvedValue([last])
  h.drill.end.mockResolvedValue({})
  h.drill.summary.mockResolvedValue(summary)
  h.segments.postAttempt.mockResolvedValue({ id: 99, score_json: green })
  h.rec.start.mockResolvedValue(undefined)
  h.rec.stop.mockReturnValue(new Float32Array(44100))
  h.findSilenceEnd.mockReset().mockReturnValue(null)
  h.player.play.mockImplementation(() => Promise.resolve())
  h.playSequence.mockImplementation(() => Promise.resolve())
  h.takePeaks = new Float32Array(4)
  h.twoTrack = null
  useSettings.setState({ referenceVolume: 1, guideLevel: 0.5, practice: { ...useSettings.getState().practice, hideTextWhileRecording: true } })
  globalThis.AudioContext = class { sampleRate = 44100; close = () => Promise.resolve(); get currentTime() { return 0 } } as unknown as typeof AudioContext
  URL.createObjectURL = vi.fn(() => 'blob:take')
  URL.revokeObjectURL = vi.fn()
})
afterEach(async () => {
  cleanup()
  // The runner's unmount ends its session a tick later; let that happen before the next test resets the mocks.
  await new Promise((r) => setTimeout(r, 0))
  globalThis.AudioContext = origAudioContext
  URL.createObjectURL = origCreate; URL.revokeObjectURL = origRevoke
})

describe('<Drill> start screen', () => {
  it("shows today's focus with its mean, two alternatives and the last drill", async () => {
    renderAt()
    expect(await screen.findByText("Today's focus")).toBeInTheDocument()
    expect(screen.getByText('tone 3 (low)')).toBeInTheDocument()
    expect(screen.getByText('your mean 42 · 120 syllables')).toBeInTheDocument()
    expect(screen.getByText('tone pair 3→3')).toBeInTheDocument()
    expect(screen.getByText('在 zài')).toBeInTheDocument()
    expect(screen.queryByText('tone 2 (rising)')).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Start' })).toHaveLength(3)
    expect(screen.getByText('Last drill: tone 4 (falling) · 52 → 71')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'See summary' })).toBeInTheDocument()
    expect(h.drill.recent).toHaveBeenCalledWith(1)
  })

  it('Start starts that focus and hands the session to the runner', async () => {
    h.drill.start.mockResolvedValue({ ...run(twoItems), kind: 'char', key: '在', label: '在 zài' })
    renderAt()
    await screen.findByText("Today's focus")
    fireEvent.click(screen.getAllByRole('button', { name: 'Start' })[2])
    expect(h.drill.start).toHaveBeenCalledWith({ kind: 'char', key: '在' })
    expect(await screen.findByText('Sentence 1 / 2')).toBeInTheDocument()
    expect(screen.getByText('在 zài')).toBeInTheDocument()
    expect(screen.queryByText("Today's focus")).not.toBeInTheDocument()
    await flush()
  })

  it('?kind=&key= starts that focus immediately, skipping the start screen', async () => {
    h.drill.start.mockResolvedValue({ ...run([twoItems[0]]), kind: 'pair', key: '3-3', label: 'tone pair 3→3' })
    renderAt('/drill?kind=pair&key=3-3')
    expect(await screen.findByText('Sentence 1 / 1')).toBeInTheDocument()
    expect(h.drill.start).toHaveBeenCalledTimes(1)
    expect(h.drill.start).toHaveBeenCalledWith({ kind: 'pair', key: '3-3' })
    expect(screen.queryByText("Today's focus")).not.toBeInTheDocument()
    await flush()
  })

  it('without a qualifying focus explains why and links to the Library', async () => {
    h.drill.focuses.mockResolvedValue({ focuses: [], auto: null })
    h.drill.recent.mockResolvedValue([])
    renderAt()
    expect(await screen.findByText("Practise a few sentences first — drills start once there's enough to know your weak spots.")).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open the Library' })).toHaveAttribute('href', '/library')
    expect(screen.queryByRole('button', { name: 'Start' })).not.toBeInTheDocument()
  })

  it('a focus with no sentences shows a readable message', async () => {
    h.drill.start.mockRejectedValue(new ApiError(404, 'Not Found', '{"detail":"no sentences contain this focus"}', 'no sentences contain this focus'))
    renderAt()
    await screen.findByText("Today's focus")
    fireEvent.click(screen.getAllByRole('button', { name: 'Start' })[0])
    expect(await screen.findByText('No sentences contain this focus yet.')).toBeInTheDocument()
    expect(screen.getByText("Today's focus")).toBeInTheDocument()
  })

  it('a sound drill refused while sound checking is off shows the backend reason', async () => {
    const detail = 'sound checking is off: CUDA out of memory'
    h.drill.start.mockRejectedValue(new ApiError(409, 'Conflict', JSON.stringify({ detail }), detail))
    renderAt()
    await screen.findByText("Today's focus")
    fireEvent.click(screen.getAllByRole('button', { name: 'Start' })[0])
    expect(await screen.findByText(`Could not start the drill: ${detail}`)).toBeInTheDocument()
  })
})

describe('<Drill> runner', () => {
  // Starts today's focus; the reference clip of the listen step "plays" at once, so the run waits at record.
  async function startRun(items = twoItems) {
    h.drill.start.mockResolvedValue(run(items))
    const r = renderAt()
    await screen.findByText("Today's focus")
    fireEvent.click(screen.getAllByRole('button', { name: 'Start' })[0])
    await screen.findByText(`Sentence 1 / ${items.length}`)
    expect(await screen.findByText('Your turn — Enter to record')).toBeInTheDocument()
    return r
  }
  const take = async () => { press('Enter'); await flush(); press('Enter'); await flush() }

  it('listens along at the guide level, records, uploads as a drill take and moves on once the targets are green', async () => {
    await startRun()
    expect(screen.getByText('tone 3 (low)')).toBeInTheDocument()
    expect(screen.getByText('Try 1 / 3')).toBeInTheDocument()
    expect(screen.getByText('Lesson A')).toBeInTheDocument()
    expect(h.player.play).toHaveBeenCalledWith('/seg/11.opus', 1, expect.any(Function))
    expect(h.player.setVolume).toHaveBeenCalledWith(0.5)
    await take()
    expect(h.segments.postAttempt).toHaveBeenCalledWith(11, expect.any(Blob), { mode: 'drill', drill_session_id: 7 })
    expect(h.playSequence).toHaveBeenCalledWith(h.player, [expect.objectContaining({ url: '/seg/11.opus' }), expect.objectContaining({ url: 'blob:take' })], 250, expect.anything())
    expect(await screen.findByRole('button', { name: 'Next' })).toBeInTheDocument()
    expect(h.twoTrack?.score).toEqual(green)
    press('Enter')
    expect(await screen.findByText('Sentence 2 / 2')).toBeInTheDocument()
    expect(screen.getByText('Try 1 / 3')).toBeInTheDocument()
    await flush()
    expect(h.player.play).toHaveBeenLastCalledWith('/seg/12.opus', 1, expect.any(Function))
  })

  it('stops recording by itself after the silence that follows your speech, as Echo does', async () => {
    h.segments.postAttempt.mockResolvedValue({ id: 1, score_json: green })
    await startRun()
    press('Enter'); await flush()
    expect(h.rec.start).toHaveBeenCalled()
    expect(h.segments.postAttempt).not.toHaveBeenCalled()
    h.findSilenceEnd.mockReturnValue(1.0)
    await waitFor(() => expect(h.segments.postAttempt).toHaveBeenCalledWith(11, expect.any(Blob), { mode: 'drill', drill_session_id: 7 }))
    expect(h.rec.stop).toHaveBeenCalledTimes(1)
  })

  it('retries while the targets are not green, and moves on after the third scored try', async () => {
    h.segments.postAttempt.mockResolvedValue({ id: 99, score_json: notGreen })
    await startRun()
    await take()
    expect(await screen.findByRole('button', { name: 'Again' })).toBeInTheDocument()
    expect(screen.getByText('Try 1 / 3')).toBeInTheDocument()
    await take() // Enter = Again (and records), Enter stops
    expect(await screen.findByText('Try 2 / 3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Again' })).toBeInTheDocument()
    await take()
    expect(await screen.findByText('Try 3 / 3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Next' })).toBeInTheDocument()
    expect(h.segments.postAttempt).toHaveBeenCalledTimes(3)
    press('Enter')
    expect(await screen.findByText('Sentence 2 / 2')).toBeInTheDocument()
    await flush()
  })

  it("follows the session's max_tries ([drill] max_tries)", async () => {
    h.segments.postAttempt.mockResolvedValue({ id: 99, score_json: notGreen })
    h.drill.start.mockResolvedValue({ ...run(twoItems), max_tries: 2 })
    renderAt()
    await screen.findByText("Today's focus")
    fireEvent.click(screen.getAllByRole('button', { name: 'Start' })[0])
    expect(await screen.findByText('Your turn — Enter to record')).toBeInTheDocument()
    expect(screen.getByText('Try 1 / 2')).toBeInTheDocument()
    await take()
    expect(await screen.findByRole('button', { name: 'Again' })).toBeInTheDocument()
    await take()
    expect(await screen.findByText('Try 2 / 2')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Next' })).toBeInTheDocument()
  })

  it('a gate-warning take shows the warning and does not count as a try', async () => {
    h.segments.postAttempt.mockResolvedValueOnce({ id: 98, score_json: gated }).mockResolvedValueOnce({ id: 99, score_json: green })
    await startRun()
    await take()
    expect(await screen.findByText(QUIET)).toBeInTheDocument()
    expect(screen.getByText('Try 1 / 3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Again' })).toBeInTheDocument()
    await take()
    expect(await screen.findByRole('button', { name: 'Next' })).toBeInTheDocument()
    expect(screen.getByText('Try 1 / 3')).toBeInTheDocument()
    expect(screen.queryByText(QUIET)).not.toBeInTheDocument()
  })

  const dropped = { id: null, dropped: true, score_json: gated }

  it('a dropped take shows the warning, costs no try, and leaves no take to show or replay', async () => {
    h.segments.postAttempt.mockResolvedValueOnce(dropped).mockResolvedValueOnce({ id: 99, score_json: green })
    await startRun()
    await take()
    expect(await screen.findByText(QUIET)).toBeInTheDocument()
    expect(screen.getByText('Try 1 / 3')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Again' })).toBeInTheDocument()
    expect(h.twoTrack?.youPeaks).toBeNull()
    expect(screen.getByRole('button', { name: '▶ R' })).toBeDisabled()
    h.player.play.mockClear()
    press('r'); await flush()
    expect(h.player.play).not.toHaveBeenCalled()
    expect(h.player.playRange).not.toHaveBeenCalled()
    await take()
    expect(await screen.findByRole('button', { name: 'Next' })).toBeInTheDocument()
    expect(screen.getByText('Try 1 / 3')).toBeInTheDocument()
  })

  it('a take dropped while the reference plays back stops that playback', async () => {
    let answer!: (a: typeof dropped) => void
    h.segments.postAttempt.mockReturnValueOnce(new Promise((r) => { answer = r }))
    let signal: AbortSignal | undefined
    h.playSequence.mockImplementation(((_p: unknown, _items: unknown, _gap: unknown, s: AbortSignal) => { signal = s; return new Promise(() => {}) }) as unknown as () => Promise<void>)
    await startRun()
    await take()
    expect(signal!.aborted).toBe(false)
    await act(async () => { answer(dropped) }); await flush()
    expect(signal!.aborted).toBe(true)
    expect(await screen.findByText(QUIET)).toBeInTheDocument()
  })

  it('plays your take back from where your voice starts, after recording and on R', async () => {
    h.takePeaks = Float32Array.from({ length: 100 }, (_, b) => (b >= 20 && b <= 60 ? 0.5 : 0.001))
    const b = speechBounds(h.takePeaks, 1)!
    await startRun()
    await take()
    const [, items] = h.playSequence.mock.calls[0] as unknown as [unknown, { url: string; from?: number; to?: number }[]]
    expect(items[1]).toMatchObject({ url: 'blob:take', from: b.from, to: b.to })
    await screen.findByRole('button', { name: 'Next' })
    press('r')
    expect(h.player.playRange).toHaveBeenLastCalledWith('blob:take', 1, b.from, b.to, expect.any(Function))
    expect(h.twoTrack?.youPeaks).toBe(h.takePeaks)
  })

  it('outlines the target syllables of the current sentence', async () => {
    await startRun()
    expect(h.twoTrack?.highlight).toEqual([0, 1])
    await take()
    press('Enter'); await screen.findByText('Sentence 2 / 2'); await flush()
    expect(h.twoTrack?.highlight).toEqual([0, 1, 2])
  })

  it('an upload error (lesson rebuilding) shows in the hint line and costs no try', async () => {
    h.segments.postAttempt.mockRejectedValueOnce(new ApiError(409, 'Conflict', '{"detail":"lesson is rebuilding"}', 'lesson is rebuilding'))
    await startRun()
    await take()
    expect(await screen.findByText('Upload failed: lesson is rebuilding')).toBeInTheDocument()
    expect(screen.getByText('Try 1 / 3')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Again' })).not.toBeInTheDocument()
    await take()
    expect(await screen.findByRole('button', { name: 'Next' })).toBeInTheDocument()
  })

  it('a take shorter than the minimum is dropped with the Practice message', async () => {
    h.rec.stop.mockReturnValue(new Float32Array(100))
    await startRun()
    await take()
    expect(await screen.findByText('Too short to keep, nothing was saved. Try again.')).toBeInTheDocument()
    expect(h.segments.postAttempt).not.toHaveBeenCalled()
    expect(screen.getByText('Your turn — Enter to record')).toBeInTheDocument()
  })

  it('hides the text while recording when the setting says so', async () => {
    await startRun()
    expect(screen.getByText('你好吗', { selector: 'p.sentence' })).toBeInTheDocument()
    press('Enter'); await flush()
    expect(screen.queryByText('你好吗', { selector: 'p.sentence' })).not.toBeInTheDocument()
    press('Enter'); await flush()
    expect(screen.getByText('你好吗', { selector: 'p.sentence' })).toBeInTheDocument()
  })

  it('R replays the take; → skips to the next sentence and after the last ends the drill', async () => {
    await startRun()
    await take()
    await screen.findByRole('button', { name: 'Next' })
    press('r')
    expect(h.player.play).toHaveBeenLastCalledWith('blob:take', 1, expect.any(Function))
    press('ArrowRight')
    expect(await screen.findByText('Sentence 2 / 2')).toBeInTheDocument()
    await flush()
    press('ArrowRight')
    expect(await screen.findByText(/target syllables first try 55 → best 72/)).toBeInTheDocument()
    expect(h.drill.end).toHaveBeenCalledWith(7)
    expect(h.drill.end.mock.invocationCallOrder[0]).toBeLessThan(h.drill.summary.mock.invocationCallOrder[0])
  })

  it('Finish shows the summary; "Drill these again" starts a new run on the sentences that never went green', async () => {
    await startRun()
    fireEvent.click(screen.getByRole('button', { name: 'Finish' }))
    expect(await screen.findByText(/target syllables first try 55 → best 72/)).toBeInTheDocument()
    expect(h.drill.end).toHaveBeenCalledTimes(1)
    expect(h.drill.summary).toHaveBeenCalledWith(7)
    h.drill.start.mockResolvedValue(run([twoItems[1]], 8))
    const again = screen.getByRole('button', { name: 'Drill these again' })
    fireEvent.click(again); fireEvent.click(again)                        // a double click starts one run
    expect(h.drill.start).toHaveBeenCalledTimes(2)
    expect(h.drill.start).toHaveBeenLastCalledWith({ kind: 'tone', key: '3', segment_ids: [12] })
    expect(await screen.findByText('Sentence 1 / 1')).toBeInTheDocument()
    await flush()
    expect(h.drill.end).toHaveBeenCalledTimes(1)
  })

  it('Done after a direct start goes back to the start screen without starting it again', async () => {
    h.drill.start.mockResolvedValue(run([twoItems[0]]))
    renderAt('/drill?kind=tone&key=3')
    await screen.findByText('Sentence 1 / 1'); await flush()
    fireEvent.click(screen.getByRole('button', { name: 'Finish' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Done' }))
    expect(await screen.findByText("Today's focus")).toBeInTheDocument()
    await flush()
    expect(h.drill.start).toHaveBeenCalledTimes(1)
    expect(h.drill.focuses).toHaveBeenCalledTimes(2) // the start screen reloads: the drill changed the means
  })

  it('says "Scoring…" once the playback is over and the score has not come back', async () => {
    let played!: () => void, scoredWith!: (v: unknown) => void
    h.playSequence.mockImplementation(() => new Promise<void>((r) => { played = r }))
    h.segments.postAttempt.mockImplementation(() => new Promise((r) => { scoredWith = r }))
    await startRun()
    await take()
    expect(screen.getByText('Listen — the original, then you')).toBeInTheDocument()
    await act(async () => { played() }); await flush()
    expect(screen.getByText('Scoring…')).toBeInTheDocument()
    await act(async () => { scoredWith({ id: 99, score_json: green }) }); await flush()
    expect(screen.getByText('Green — Enter for the next sentence')).toBeInTheDocument()
  })

  it('Finish while a take uploads waits for it before ending the drill', async () => {
    let saved!: (v: unknown) => void
    h.segments.postAttempt.mockImplementation(() => new Promise((r) => { saved = r }))
    await startRun()
    await take()
    fireEvent.click(screen.getByRole('button', { name: 'Finish' }))
    await flush()
    expect(screen.getByText('Saving your take…')).toBeInTheDocument()
    expect(h.drill.end).not.toHaveBeenCalled()
    expect(h.drill.summary).not.toHaveBeenCalled()
    await act(async () => { saved({ id: 99, score_json: notGreen }) })
    expect(await screen.findByText(/target syllables first try 55 → best 72/)).toBeInTheDocument()
    expect(h.drill.end).toHaveBeenCalledWith(7)
  })

  it('→ on the last sentence while its take uploads waits too, and a failed upload still ends the drill', async () => {
    let failed!: (e: unknown) => void
    h.segments.postAttempt.mockImplementation(() => new Promise((_, rej) => { failed = rej }))
    await startRun([twoItems[0]])
    await take()
    press('ArrowRight'); await flush()
    expect(screen.getByText('Saving your take…')).toBeInTheDocument()
    expect(h.drill.end).not.toHaveBeenCalled()
    await act(async () => { failed(new Error('network down')) })
    expect(await screen.findByText(/target syllables first try 55 → best 72/)).toBeInTheDocument()
    expect(h.drill.end).toHaveBeenCalledWith(7)
  })

  it('leaving the page mid-drill ends the session', async () => {
    const { unmount } = await startRun()
    unmount()
    await waitFor(() => expect(h.drill.end).toHaveBeenCalledWith(7))
    expect(h.drill.summary).not.toHaveBeenCalled()
  })
})

describe('<Shell>', () => {
  it('has a Drill tab after Review linking to /drill', () => {
    render(<MemoryRouter future={future}><Shell><div /></Shell></MemoryRouter>)
    const tabs = screen.getAllByRole('link').map((a) => a.textContent)
    expect(tabs.indexOf('Drill')).toBe(tabs.indexOf('Review') + 1)
    expect(screen.getByRole('link', { name: 'Drill' })).toHaveAttribute('href', '/drill')
  })
})
