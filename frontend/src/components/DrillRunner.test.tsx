import { act, cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DrillSession, Segment } from '../api/types'

const h = vi.hoisted(() => ({
  api: { segments: { audioUrl: (id: number, fmt = 'opus') => `/seg/${id}.${fmt}`, postAttempt: vi.fn() }, drill: { end: vi.fn() } },
  player: { play: vi.fn(() => Promise.resolve()), playRange: vi.fn(() => Promise.resolve()), stop: vi.fn(), setVolume: vi.fn(), preload: vi.fn(() => Promise.resolve()), peaksFor: vi.fn(() => new Promise(() => {})) },
  twoTrack: null as null | { onPlayYouSyllable?: (i: number) => void; score?: unknown },
}))
vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api/client')>()), api: h.api }))
vi.mock('../audio/player', () => ({
  ClipPlayer: class { constructor() { return h.player } },
  playSequence: () => Promise.resolve(),
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
})
