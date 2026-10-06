import { afterEach, describe, expect, it, vi } from 'vitest'
import { playClip, sleep } from './abortable'

afterEach(() => { vi.useRealTimers() })

describe('sleep', () => {
  it('resolves after the delay and leaves no listener behind', async () => {
    vi.useFakeTimers()
    const ctrl = new AbortController(), remove = vi.spyOn(ctrl.signal, 'removeEventListener')
    let done = false
    void sleep(300, ctrl.signal).then(() => { done = true })
    await vi.advanceTimersByTimeAsync(299); expect(done).toBe(false)
    await vi.advanceTimersByTimeAsync(1); expect(done).toBe(true)
    expect(remove).toHaveBeenCalledWith('abort', expect.any(Function))
  })
  it('resolves at once on abort and clears its timer', async () => {
    vi.useFakeTimers()
    const ctrl = new AbortController()
    const p = sleep(10_000, ctrl.signal)
    ctrl.abort()
    await p
    expect(vi.getTimerCount()).toBe(0)
  })
  it('does not wait when already aborted', async () => {
    vi.useFakeTimers()
    const ctrl = new AbortController(); ctrl.abort()
    await sleep(10_000, ctrl.signal)
    expect(vi.getTimerCount()).toBe(0)
  })
})

describe('playClip', () => {
  it('stops the player on abort and detaches its listener after the clip', async () => {
    let finish!: () => void
    const player = { play: vi.fn(() => new Promise<void>((r) => { finish = r })), stop: vi.fn(() => finish()) }
    const ctrl = new AbortController(), remove = vi.spyOn(ctrl.signal, 'removeEventListener')
    const p = playClip(player, '/a', 0.8, ctrl.signal)
    expect(player.play).toHaveBeenCalledWith('/a', 0.8, undefined)
    ctrl.abort()
    await p
    expect(player.stop).toHaveBeenCalledTimes(1)
    expect(remove).toHaveBeenCalledWith('abort', expect.any(Function))
  })
  it('does not play when already aborted', async () => {
    const player = { play: vi.fn(() => Promise.resolve()), stop: vi.fn() }
    const ctrl = new AbortController(); ctrl.abort()
    await playClip(player, '/a', 1, ctrl.signal)
    expect(player.play).not.toHaveBeenCalled()
  })
})
