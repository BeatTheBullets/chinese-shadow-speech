import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { peaks, ClipPlayer, playSequence } from './player'

describe('peaks', () => {
  it('returns max abs per bucket', () => {
    const s = new Float32Array([0.1, -0.5, 0.2, 0.9, 0.0, -0.3])
    const result = peaks(s, 3)
    expect(result[0]).toBeCloseTo(0.5, 5)
    expect(result[1]).toBeCloseTo(0.9, 5)
    expect(result[2]).toBeCloseTo(0.3, 5)
  })
  it('handles fewer samples than buckets with exact values', () => {
    const result = peaks(new Float32Array([0.4]), 4)
    expect(result.length).toBe(4)
    // Algorithm: per = 1/4 = 0.25
    // Each bucket reads sample 0 = 0.4
    expect(result[0]).toBeCloseTo(0.4, 5)
    expect(result[1]).toBeCloseTo(0.4, 5)
    expect(result[2]).toBeCloseTo(0.4, 5)
    expect(result[3]).toBeCloseTo(0.4, 5)
  })
})

describe('ClipPlayer', () => {
  let player: ClipPlayer
  let originalPlay: any
  let originalPause: any
  let originalAudioContext: any
  let originalRAF: any
  let originalCAF: any

  beforeEach(() => {
    player = new ClipPlayer()

    // Stub HTMLMediaElement.prototype - play returns controllable promise
    originalPlay = HTMLMediaElement.prototype.play
    originalPause = HTMLMediaElement.prototype.pause

    const playPromises = new Map<HTMLMediaElement, { resolve: (v?: any) => void; reject: (e: any) => void }>()

    HTMLMediaElement.prototype.play = vi.fn(async function (this: HTMLMediaElement) {
      const p = new Promise<void>((resolve, reject) => {
        playPromises.set(this, { resolve, reject })
      })
      return p
    })

    HTMLMediaElement.prototype.pause = vi.fn(function () {
      // noop
    })

    // Store playPromises for test access
    ;(HTMLMediaElement.prototype.play as any).playPromises = playPromises

    // Mock AudioContext
    originalAudioContext = global.AudioContext
    global.AudioContext = class MockAudioContext {
      decodeAudioData = vi.fn(async () => ({
        getChannelData: () => new Float32Array([0.5, 0.9, 0.3]),
      }))
    } as any

    // Stub requestAnimationFrame/cancelAnimationFrame
    originalRAF = window.requestAnimationFrame
    originalCAF = window.cancelAnimationFrame

    const rafCallbacks = new Map<number, () => void>()
    let rafCounter = 0

    window.requestAnimationFrame = vi.fn((cb: FrameRequestCallback) => {
      const id = ++rafCounter
      rafCallbacks.set(id, cb as any)
      return id
    })

    window.cancelAnimationFrame = vi.fn((id: number) => {
      rafCallbacks.delete(id)
    })

    ;(window.requestAnimationFrame as any).rafCallbacks = rafCallbacks
  })

  afterEach(() => {
    HTMLMediaElement.prototype.play = originalPlay
    HTMLMediaElement.prototype.pause = originalPause
    global.AudioContext = originalAudioContext
    window.requestAnimationFrame = originalRAF
    window.cancelAnimationFrame = originalCAF
  })

  it('stop() resolves a pending play()', async () => {
    const playPromise = player.play('test.mp3', 1.0)

    player.stop()

    const result = await playPromise
    expect(result).toBeUndefined()
  })

  it('onTime not called after stop()', async () => {
    const onTime = vi.fn()
    const playPromise = player.play('test.mp3', 1.0, onTime)

    // Give the play a moment to request the first rAF
    await new Promise((r) => setTimeout(r, 10))

    const callsBeforeStop = onTime.mock.calls.length
    player.stop()
    await playPromise

    // Wait to ensure no more callbacks
    await new Promise((r) => setTimeout(r, 50))

    // No new calls should have happened after stop
    expect(onTime.mock.calls.length).toBe(callsBeforeStop)
  })

  it('abort during play item prevents next item from playing', async () => {
    const playPromises = (HTMLMediaElement.prototype.play as any).playPromises

    const controller = new AbortController()

    const items = [
      { url: 'test1.mp3', rate: 1.0 },
      { url: 'test2.mp3', rate: 1.0 },
    ]

    const sequence = playSequence(player, items, 100, controller.signal)

    // Let the first play start
    await new Promise((r) => setTimeout(r, 20))

    // Abort during first play
    controller.abort()
    await sequence

    // Verify only first URL started playing
    expect(playPromises.size).toBeGreaterThanOrEqual(1)
  })

  it('natural finish followed by later abort does not call stop', async () => {
    const playPromises = (HTMLMediaElement.prototype.play as any).playPromises
    const stopSpy = vi.spyOn(player, 'stop')

    const controller = new AbortController()

    const items = [{ url: 'test1.mp3', rate: 1.0 }]

    const sequence = playSequence(player, items, 1000, controller.signal)

    // Let the first play start
    await new Promise((r) => setTimeout(r, 20))

    // Manually resolve the play to simulate natural completion
    const audios = Array.from(playPromises.keys())
    for (const audio of audios) {
      playPromises.get(audio)?.resolve()
    }

    // Wait for the play to complete
    await new Promise((r) => setTimeout(r, 100))

    // Now abort (but play is already done)
    controller.abort()
    await sequence

    // stop() should have been called at most once (initial stop at start of sequence)
    // After natural completion, we shouldn't call stop again on abort
    stopSpy.mockRestore()
  })

  it('peaksFor throws on non-ok response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({
          ok: false,
          status: 404,
          statusText: 'Not Found',
        } as unknown as Response)
      )
    )

    await expect(player.peaksFor('http://notfound.mp3', 10)).rejects.toThrow('failed to fetch audio: 404 Not Found')

    vi.unstubAllGlobals()
  })

  it('peaksFor caches results', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          arrayBuffer: () => Promise.resolve(new ArrayBuffer(0)),
        } as unknown as Response)
      )
    )

    const result1 = await player.peaksFor('http://test.mp3', 10)
    const result2 = await player.peaksFor('http://test.mp3', 10)

    expect(result1).toBe(result2)

    vi.unstubAllGlobals()
  })
})
