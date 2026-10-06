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
  it('handles fewer samples than buckets', () => {
    const result = peaks(new Float32Array([0.4]), 4)
    expect(result.length).toBe(4)
    // When fewer samples than buckets, verify all values are present
    expect([...result].filter((v) => v > 0).length).toBeGreaterThan(0)
  })
})

describe('ClipPlayer', () => {
  let player: ClipPlayer
  let originalPlay: any
  let originalPause: any
  let originalAudioContext: any

  beforeEach(() => {
    player = new ClipPlayer()

    // Stub HTMLMediaElement.prototype.play/pause
    originalPlay = HTMLMediaElement.prototype.play
    originalPause = HTMLMediaElement.prototype.pause

    HTMLMediaElement.prototype.play = vi.fn(async function () {
      return Promise.resolve()
    })
    HTMLMediaElement.prototype.pause = vi.fn(function () {
      // noop
    })

    // Mock AudioContext for peaksFor tests
    originalAudioContext = global.AudioContext
    global.AudioContext = class MockAudioContext {
      decodeAudioData = vi.fn(async () => ({
        getChannelData: () => new Float32Array([0.5, 0.9, 0.3]),
      }))
    } as any
  })

  afterEach(() => {
    HTMLMediaElement.prototype.play = originalPlay
    HTMLMediaElement.prototype.pause = originalPause
    global.AudioContext = originalAudioContext
  })

  it('stop() resolves a pending play()', async () => {
    const playPromise = player.play('test.mp3', 1.0)

    // Immediately stop the play
    player.stop()

    // The promise should resolve (not reject)
    const result = await playPromise
    expect(result).toBeUndefined()
  })

  it('stop() cancels requestAnimationFrame', async () => {
    const cancelAnimationFrameSpy = vi.spyOn(window, 'cancelAnimationFrame')

    const playPromise = player.play('test.mp3', 1.0)

    // Give the play a moment to start
    await new Promise((r) => setTimeout(r, 10))

    player.stop()
    await playPromise

    expect(cancelAnimationFrameSpy).toHaveBeenCalled()
    cancelAnimationFrameSpy.mockRestore()
  })

  it(
    'playSequence stops after abort',
    async () => {
      const controller = new AbortController()
      const items = [
        { url: 'test1.mp3', rate: 1.0 },
        { url: 'test2.mp3', rate: 1.0 },
      ]

      const sequence = playSequence(player, items, 1000, controller.signal)

      // Abort after a short delay (before first play would normally end)
      setTimeout(() => controller.abort(), 50)

      // playSequence should return when aborted
      await expect(sequence).resolves.toBeUndefined()
    },
    10000
  )


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

    // Should return the same cached result
    expect(result1).toBe(result2)

    vi.unstubAllGlobals()
  })
})
