import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DrillSession, Segment } from '../api/types'

const h = vi.hoisted(() => ({
  api: { segments: { audioUrl: (id: number, fmt = 'opus') => `/seg/${id}.${fmt}`, postAttempt: vi.fn() }, drill: { end: vi.fn() } },
  player: { play: vi.fn(() => Promise.resolve()), playRange: vi.fn(() => Promise.resolve()), stop: vi.fn(), setVolume: vi.fn(), preload: vi.fn(() => Promise.resolve()), peaksFor: vi.fn(() => new Promise(() => {})) },
  twoTrack: null as null | { onPlayYouSyllable?: (i: number) => void; onPlaySyllable?: (i: number) => void; onCompareSyllable?: (i: number) => void; score?: unknown },
  playSequence: vi.fn<(...a: unknown[]) => Promise<void>>(() => Promise.resolve()),
}))
vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api/client')>()), api: h.api }))
vi.mock('../audio/player', () => ({
  ClipPlayer: class { constructor() { return h.player } },
  playSequence: h.playSequence,
  peaks: () => new Float32Array(4),
}))
vi.mock('../audio/abortable', () => ({ playClip: () => Promise.resolve() }))
vi.mock('../audio/recorder', () => ({ toWav16k: () => new Blob(['wav']), Recorder: class {} }))
vi.mock('../audio/useMic', () => {
  let on = false
  const mic = {
    open: async () => { on = true; return null }, abandon: () => { on = false }, capturing: () => on, now: () => 0, snapshot: () => null,
    finish: () => { on = false; return { rec: { sampleRate: 44100 }, samples: new Float32Array(44100) } },
  }
  return { useMic: () => mic }
})
vi.mock('./TwoTrack', () => ({
  default: (p: NonNullable<typeof h.twoTrack>) => { h.twoTrack = p; return <div data-testid="two-track" /> },
}))

import { useSettings } from '../store/settings'
import DrillRunner from './DrillRunner'

const seg: Segment = {
  id: 11, lesson_id: 1, idx: 0, start_s: 0, end_s: 2, text: '你好吗', translation: null, words_json: null, ref_alignment_json: null,
  difficulty_flag: false, anki_note_id: null, last_score: null, best_score: null, attempts: 0,
}
const session: DrillSession = { id: 7, kind: 'sound', key: 'x', label: 'Sounds', short: false, items: [{ segment: seg, lesson_id: 1, lesson_title: 'L', targets: [0] }] }
const syl = (status: string) => ({ ch: '你', pinyin: 'nǐ', tone: 3, target_tone: 3, heard_tone: 3, status, tone_score: 0.9, p_target: 0.9, contour: 0.9 })
const score = {
  overall: 0.8, tone_overall: 0.8, segmental_overall: null, rate_ratio: 1, ref_contour: null, warnings: [],
  usr_contour: { t0_s: 0, step_ms: 10, f0_st: [], spans: [[0.1, 0.4], [0.4, 0.9], [0.9, 0.91]] },
  syllables: [syl('ok'), syl('unvoiced'), syl('missing')],
}

describe('<DrillRunner> your syllable', () => {
  const origCreate = URL.createObjectURL, origRevoke = URL.revokeObjectURL
  beforeEach(() => {
    vi.clearAllMocks()
    useSettings.setState({ helpSeen: true })
    h.api.drill.end.mockResolvedValue({})
    h.api.segments.postAttempt.mockResolvedValue({ id: 99, score_json: score })
    URL.createObjectURL = vi.fn(() => 'blob:take'); URL.revokeObjectURL = vi.fn()
  })
  afterEach(() => { cleanup(); URL.createObjectURL = origCreate; URL.revokeObjectURL = origRevoke })

  it('plays a normal cell’s span of the take; missing and unvoiced cells play nothing', async () => {
    render(<DrillRunner session={session} onFinish={() => {}} />)
    const flush = () => act(async () => { for (let i = 0; i < 10; i++) await Promise.resolve() })
    await flush()
    fireEvent.keyDown(window, { key: 'Enter' }); await flush() // start the take
    fireEvent.keyDown(window, { key: 'Enter' }); await flush() // stop it; it uploads and scores
    await waitFor(() => expect(h.twoTrack?.score).toEqual(score))
    act(() => h.twoTrack!.onPlayYouSyllable!(0)); await flush()
    expect(h.player.playRange).toHaveBeenCalledTimes(1)
    expect(h.player.playRange).toHaveBeenCalledWith('blob:take', 1, 0.1, 0.4, expect.any(Function))
    act(() => h.twoTrack!.onPlayYouSyllable!(1)); await flush()
    act(() => h.twoTrack!.onPlayYouSyllable!(2)); await flush()
    expect(h.player.playRange).toHaveBeenCalledTimes(1)
  })

  it('clicking a character on the sentence card plays that syllable of the reference', async () => {
    const aligned: Segment = { ...seg, start_s: 10, end_s: 12, ref_alignment_json: [
      { ch: '你', start: 10.2, end: 10.5, conf: 1 }, { ch: '好', start: 10.5, end: 11.25, conf: 1 }, { ch: '吗', start: 11.25, end: 11.5, conf: 1 }] }
    // jsdom does no layout: each character gets a 40 px box at 40 px × its offset, so x = 40 i + 20 is on character i.
    const orig = Range.prototype.getClientRects
    Range.prototype.getClientRects = function (this: Range) { return [{ left: this.startOffset * 40, top: 0, width: 40, height: 40 }] as unknown as DOMRectList }
    try {
      render(<DrillRunner session={{ ...session, items: [{ ...session.items[0], segment: aligned }] }} onFinish={() => {}} />)
      const flush = () => act(async () => { for (let i = 0; i < 10; i++) await Promise.resolve() })
      await flush()
      fireEvent.keyDown(window, { key: 'Enter' }); await flush() // a take, so the step is past listening
      fireEvent.keyDown(window, { key: 'Enter' }); await flush()
      await waitFor(() => expect(h.twoTrack?.score).toEqual(score))
      fireEvent.click(screen.getByText('你好吗', { selector: 'p.sentence' }), { clientX: 60, clientY: 20 }); await flush()
      expect(h.player.playRange).toHaveBeenCalledTimes(1)
      const [url, , from, to] = h.player.playRange.mock.calls[0] as unknown as [string, number, number, number]
      expect(url).toBe('/seg/11.wav'); expect(from).toBeCloseTo(0.5, 5); expect(to).toBeCloseTo(1.25, 5)
    } finally { Range.prototype.getClientRects = orig }
  })

  it('a verdict cell’s speaker plays the reference syllable at the drill’s speed; its character the speaker, a pause, then you', async () => {
    const aligned: Segment = { ...seg, start_s: 10, end_s: 12, ref_alignment_json: [
      { ch: '你', start: 10.2, end: 10.5, conf: 1 }, { ch: '好', start: 10.5, end: 11.25, conf: 1 }, { ch: '吗', start: 11.25, end: 11.5, conf: 1 }] }
    render(<DrillRunner session={{ ...session, items: [{ ...session.items[0], segment: aligned }] }} onFinish={() => {}} />)
    const flush = () => act(async () => { for (let i = 0; i < 10; i++) await Promise.resolve() })
    await flush()
    fireEvent.keyDown(window, { key: 'Enter' }); await flush()
    fireEvent.keyDown(window, { key: 'Enter' }); await flush()
    await waitFor(() => expect(h.twoTrack?.score).toEqual(score))
    fireEvent.keyDown(window, { key: 's' }); await flush()        // the drill's reference at 0.75: the take must stay at 1
    h.player.playRange.mockClear(); h.playSequence.mockClear()
    act(() => h.twoTrack!.onPlaySyllable!(1)); await flush()
    expect(h.player.playRange).toHaveBeenCalledTimes(1)
    const [url, rate, from, to] = h.player.playRange.mock.calls[0] as unknown as [string, number, number, number]
    expect([url, rate]).toEqual(['/seg/11.wav', 0.75]); expect(from).toBeCloseTo(0.5, 5); expect(to).toBeCloseTo(1.25, 5)
    act(() => h.twoTrack!.onCompareSyllable!(0)); await flush()
    expect(h.playSequence).toHaveBeenCalledTimes(1)
    const [, items, gap] = h.playSequence.mock.calls[0] as unknown as [unknown, { url: string; rate: number; from: number; to: number }[], number]
    expect(gap).toBe(250)
    expect(items.map((i) => [i.url, i.rate])).toEqual([['/seg/11.wav', 0.75], ['blob:take', 1]])
    expect(items[0].from).toBeCloseTo(0.2, 5); expect(items[0].to).toBeCloseTo(0.5, 5)
    expect([items[1].rate, items[1].from, items[1].to]).toEqual([1, 0.1, 0.4])
    act(() => h.twoTrack!.onCompareSyllable!(2)); await flush()     // missing: the speaker alone
    const [, only] = h.playSequence.mock.calls[1] as unknown as [unknown, { url: string }[]]
    expect(only.map((i) => i.url)).toEqual(['/seg/11.wav'])
  })

  it('the drill stage is the same slim line as Echo’s: no reserved room under the card', async () => {
    render(<DrillRunner session={session} onFinish={() => {}} />)
    await act(async () => { for (let i = 0; i < 10; i++) await Promise.resolve() })
    expect(screen.getByTestId('stage-cue')).toHaveClass('min-h-8')
    expect(screen.getByTestId('stage-cue')).not.toHaveClass('min-h-28')
  })
})
