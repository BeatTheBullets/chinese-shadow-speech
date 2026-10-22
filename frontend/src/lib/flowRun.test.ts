import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AFTER_PAUSE_MS, CLIP_GRACE_MS, playFlow, type FlowClip } from './flowRun'

const clips: FlowClip[] = [
  { segmentId: 1, idx: 0, url: '/1', duration: 2 },
  { segmentId: 2, idx: 1, url: '/2', duration: 1 },
]
let clock = 0
let pending: { url: string; resolve: () => void }[] = []
const player = {
  play: vi.fn((url: string) => new Promise<void>((resolve) => { pending.push({ url, resolve }) })),
  stop: vi.fn(() => { pending.splice(0).forEach((p) => p.resolve()) }),
  preload: vi.fn(() => Promise.resolve()),
}
// Ends the clip now playing after `secs` of clock time.
const finishClip = async (secs: number) => { clock += secs; pending.shift()!.resolve(); await vi.advanceTimersByTimeAsync(0) }
let skips: AbortController[] = []
const start = (sub: 'after' | 'along', signal = new AbortController().signal, rate = 1) =>
  playFlow({ player, clock: () => clock, clips, sub, gapFactor: 1.1, rate: () => rate, signal, onClip: (_c, skip) => { skips.push(skip) } })

beforeEach(() => { vi.useFakeTimers(); vi.clearAllMocks(); clock = 10; pending = []; skips = [] })
afterEach(() => { vi.useRealTimers() })

describe('playFlow', () => {
  it('a clip that never loads trips the watchdog after duration / rate + grace, keeping the earlier clips', async () => {
    const run = start('along', undefined, 0.5)
    await vi.advanceTimersByTimeAsync(0)
    await finishClip(2)
    // clip 2 (1 s at half speed = 2 s) never settles: nothing before duration / rate + grace
    await vi.advanceTimersByTimeAsync(2000 + CLIP_GRACE_MS - 1)
    expect(player.stop).not.toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(1)
    const r = await run
    expect(player.stop).toHaveBeenCalled()
    expect((r.error as Error).message).toMatch(/did not load/)
    expect(r.actual.filter((a) => a.playEnd != null).map((a) => a.idx)).toEqual([0])
    expect(vi.getTimerCount()).toBe(0)
  })

  it('a stop during a clip clears the watchdog timer', async () => {
    const ctrl = new AbortController()
    const run = start('along', ctrl.signal)
    await vi.advanceTimersByTimeAsync(0)
    ctrl.abort()
    const r = await run
    expect(r.error).toBeNull()
    expect(vi.getTimerCount()).toBe(0)
  })

  it('along: plays the clips back to back and stamps each on the recording clock', async () => {
    const run = start('along')
    await vi.advanceTimersByTimeAsync(0)
    await finishClip(2)
    expect(player.play).toHaveBeenLastCalledWith('/2', 1, undefined) // no wait between clips
    await finishClip(1)
    const r = await run
    expect(r.actual).toEqual([
      { segmentId: 1, idx: 0, playStart: 10, playEnd: 12, refDuration: 2 },
      { segmentId: 2, idx: 1, playStart: 12, playEnd: 13, refDuration: 1 },
    ])
    expect(r.skipped).toBe(0)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('after: waits gap_factor × heard duration plus a short pause before the next clip', async () => {
    const run = start('after', undefined, 0.8)
    await vi.advanceTimersByTimeAsync(0)
    expect(player.play).toHaveBeenCalledWith('/1', 0.8, undefined)
    await finishClip(2.5)
    const gapMs = (2 / 0.8) * 1.1 * 1000 + AFTER_PAUSE_MS
    await vi.advanceTimersByTimeAsync(gapMs - 1)
    expect(player.play).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(player.play).toHaveBeenCalledTimes(2)
    await finishClip(1.25)
    await vi.advanceTimersByTimeAsync((1 / 0.8) * 1.1 * 1000 + AFTER_PAUSE_MS)
    const r = await run
    expect(r.actual[0]).toMatchObject({ refDuration: 2.5, playEnd: 12.5 })
  })

  it('stop mid-clip: finished clips keep their stamps, the interrupted one has no playEnd', async () => {
    const stop = new AbortController()
    const run = start('along', stop.signal)
    await vi.advanceTimersByTimeAsync(0)
    await finishClip(2)
    stop.abort()
    const r = await run
    expect(player.stop).toHaveBeenCalled()
    expect(r.actual.map((a) => a.playEnd)).toEqual([12, undefined])
    expect(r.skipped).toBe(0)
  })

  it('stop during the after-gap drops that sentence (the learner may be mid-word) and plays nothing more', async () => {
    const stop = new AbortController()
    const run = start('after', stop.signal)
    await vi.advanceTimersByTimeAsync(0)
    await finishClip(2)
    await vi.advanceTimersByTimeAsync(500)
    stop.abort()
    const r = await run
    expect(r.actual).toHaveLength(1)
    expect(r.actual[0].playEnd).toBeUndefined()
    expect(r.skipped).toBe(0) // stopped, not skipped
    expect(player.play).toHaveBeenCalledTimes(1)
    expect(vi.getTimerCount()).toBe(0)
  })

  it('skip drops the current sentence and moves straight on', async () => {
    const run = start('after')
    await vi.advanceTimersByTimeAsync(0)
    skips[0].abort()
    await vi.advanceTimersByTimeAsync(0)
    expect(player.play).toHaveBeenLastCalledWith('/2', 1, undefined)
    await finishClip(1)
    await vi.advanceTimersByTimeAsync(1.1 * 1000 + AFTER_PAUSE_MS)
    const r = await run
    expect(r.skipped).toBe(1)
    expect(r.actual.map((a) => a.playEnd)).toEqual([undefined, expect.any(Number)])
  })

  it('a playback error ends the run and keeps what was played', async () => {
    player.play.mockImplementationOnce(() => Promise.resolve()).mockImplementationOnce(() => Promise.reject(new Error('audio error')))
    const r = await start('along')
    expect(r.error).toBeInstanceOf(Error)
    expect(r.actual.map((a) => a.playEnd)).toEqual([10, undefined])
  })

  it('after: opens the speaking window when a clip ends and closes it before the next clip', async () => {
    const turns: (number | null)[] = []
    const run = playFlow({ player, clock: () => clock, clips, sub: 'after', gapFactor: 1.1, rate: () => 1, signal: new AbortController().signal,
      onClip: () => {}, onTurn: (_c, t) => { turns.push(t && t.duration) } })
    await vi.advanceTimersByTimeAsync(0)
    await finishClip(2)
    expect(turns).toEqual([2.2])
    await vi.advanceTimersByTimeAsync(2600)
    expect(turns).toEqual([2.2, null])
    await finishClip(1)
    await vi.advanceTimersByTimeAsync(1500)
    await run
    expect(turns).toEqual([2.2, null, 1.1, null])
  })

  it('after: the speaking window closes when its time is up, before the short pause ahead of the next clip', async () => {
    const turns: (number | null)[] = []
    const run = playFlow({ player, clock: () => clock, clips, sub: 'after', gapFactor: 1.1, rate: () => 1, signal: new AbortController().signal,
      onClip: () => {}, onTurn: (_c, t) => { turns.push(t && t.duration) } })
    await vi.advanceTimersByTimeAsync(0)
    await finishClip(2)
    await vi.advanceTimersByTimeAsync(2199)
    expect(turns).toEqual([2.2])
    await vi.advanceTimersByTimeAsync(1)
    expect(turns).toEqual([2.2, null])        // the bar has run out exactly as the window ends
    expect(player.play).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(AFTER_PAUSE_MS)
    expect(player.play).toHaveBeenCalledTimes(2)
    await finishClip(1)
    await vi.advanceTimersByTimeAsync(1500)
    await run
  })

  it('after: skipping during the short pause still drops the sentence', async () => {
    const run = start('after')
    await vi.advanceTimersByTimeAsync(0)
    await finishClip(2)
    await vi.advanceTimersByTimeAsync(2200 + 100)
    skips[0].abort()
    await vi.advanceTimersByTimeAsync(0)
    await finishClip(1)
    await vi.advanceTimersByTimeAsync(1500)
    const r = await run
    expect(r.skipped).toBe(1)
    expect(r.actual[0].playEnd).toBeUndefined()
  })

  it('after: stopping during the speaking window closes it', async () => {
    const turns: (number | null)[] = []
    const stop = new AbortController()
    const run = playFlow({ player, clock: () => clock, clips, sub: 'after', gapFactor: 1.1, rate: () => 1, signal: stop.signal,
      onClip: () => {}, onTurn: (_c, t) => { turns.push(t && t.duration) } })
    await vi.advanceTimersByTimeAsync(0)
    await finishClip(2)
    await vi.advanceTimersByTimeAsync(500)
    stop.abort()
    await run
    expect(turns).toEqual([2.2, null])
    expect(vi.getTimerCount()).toBe(0)
  })

  it('passes the clip-time callback to the player', async () => {
    const onTime = vi.fn()
    const run = playFlow({ player, clock: () => clock, clips: clips.slice(0, 1), sub: 'along', gapFactor: 1.1, rate: () => 1,
      signal: new AbortController().signal, onClip: () => {}, onTime })
    await vi.advanceTimersByTimeAsync(0)
    expect(player.play).toHaveBeenCalledWith('/1', 1, onTime)
    await finishClip(2)
    await run
  })
})
