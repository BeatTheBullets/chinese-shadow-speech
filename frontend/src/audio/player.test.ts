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
    expect(result[0]).toBeCloseTo(0.4, 5)
    expect(result[1]).toBeCloseTo(0.4, 5)
    expect(result[2]).toBeCloseTo(0.4, 5)
    expect(result[3]).toBeCloseTo(0.4, 5)
  })
})

describe('ClipPlayer', () => {
  let player: ClipPlayer
  let originalPlay: HTMLMediaElement['play']
  let originalPause: HTMLMediaElement['pause']
  let originalAudioContext: typeof AudioContext
  let originalAudio: typeof Audio
  let originalRAF: typeof window.requestAnimationFrame
  let originalCAF: typeof window.cancelAnimationFrame
  let rafQueue: { id: number; callback: FrameRequestCallback }[]
  let rafCounter: number
  let audioElements: Map<HTMLAudioElement, { ended: boolean; url?: string }>

  beforeEach(() => {
    player = new ClipPlayer()
    rafQueue = []
    rafCounter = 0
    audioElements = new Map()

    // Save originals
    originalPlay = HTMLMediaElement.prototype.play
    originalPause = HTMLMediaElement.prototype.pause
    originalRAF = window.requestAnimationFrame
    originalCAF = window.cancelAnimationFrame
    originalAudioContext = global.AudioContext
    originalAudio = window.Audio

    // Stub play to return resolved promise
    HTMLMediaElement.prototype.play = vi.fn(async function (this: HTMLMediaElement) {
      return Promise.resolve()
    })

    // Stub pause
    HTMLMediaElement.prototype.pause = vi.fn(function (this: HTMLMediaElement) {
      // noop
    })

    // Manual rAF/cAF queue
    window.requestAnimationFrame = vi.fn((cb: FrameRequestCallback) => {
      const id = ++rafCounter
      rafQueue.push({ id, callback: cb })
      return id
    })

    window.cancelAnimationFrame = vi.fn((id: number) => {
      const idx = rafQueue.findIndex((item) => item.id === id)
      if (idx !== -1) rafQueue.splice(idx, 1)
    })

    // Mock AudioContext
    global.AudioContext = class MockAudioContext {
      decodeAudioData = vi.fn(async () => ({
        getChannelData: () => new Float32Array([0.5, 0.9, 0.3]),
      }))
    } as unknown as typeof AudioContext

    // Spy on Audio constructor to track elements and their ended state
    const OriginalAudio = originalAudio
    window.Audio = function (src?: string) {
      const audio = new OriginalAudio(src)
      audioElements.set(audio, { ended: false, url: src })

      // Add ended getter/setter
      Object.defineProperty(audio, 'ended', {
        get() {
          return audioElements.get(this)?.ended ?? false
        },
        set(val: boolean) {
          if (audioElements.has(this)) {
            audioElements.get(this)!.ended = val
          }
        },
        configurable: true,
      })

      return audio
    } as unknown as typeof Audio
  })

  afterEach(() => {
    HTMLMediaElement.prototype.play = originalPlay
    HTMLMediaElement.prototype.pause = originalPause
    window.requestAnimationFrame = originalRAF
    window.cancelAnimationFrame = originalCAF
    global.AudioContext = originalAudioContext
    window.Audio = originalAudio
    vi.useRealTimers()
    vi.unstubAllGlobals()
    rafQueue = []
    audioElements.clear()
  })

  it('onTime not called after stop', async () => {
    const onTime = vi.fn()
    const playPromise = player.play('test.mp3', 1.0, onTime)

    // Wait for rAF to be queued
    await Promise.resolve()
    await Promise.resolve()
    await Promise.resolve()

    expect(rafQueue.length).toBeGreaterThan(0)

    // Flush first rAF - onTime should be called
    const firstBatch = [...rafQueue]
    for (const item of firstBatch) {
      item.callback(0)
    }
    expect(onTime.mock.calls.length).toBeGreaterThan(0)
    const callsBeforeStop = onTime.mock.calls.length

    // Stop the play
    player.stop()
    await playPromise

    // Flush more rAF callbacks - should not call onTime again
    for (const item of rafQueue) {
      item.callback(0)
    }

    expect(onTime.mock.calls.length).toBe(callsBeforeStop)
  })

  it('stale ended event does not resolve new play of same URL', async () => {
    // Play once
    const play1 = player.play('test.mp3', 1.0)
    await Promise.resolve()

    // Stop the first play
    player.stop()
    await play1

    // Start second play of same URL (reuses cached element)
    const play2 = player.play('test.mp3', 1.0)
    await Promise.resolve()

    // Get the current audio element
    const audioList = Array.from(audioElements.keys())
    const audio = audioList[audioList.length - 1]

    // Dispatch ended event while element.ended is false (stale event from before)
    audio.dispatchEvent(new Event('ended'))

    // Second play should NOT resolve (stale event should be ignored because a.ended is false)
    let play2Resolved = false
    play2.then(() => { play2Resolved = true })
    await new Promise((r) => setTimeout(r, 50))
    expect(play2Resolved).toBe(false)
    expect(player['current']).toBe(audio)

    // Clean up
    player.stop()
  })

  it('abort during item prevents next item from playing', async () => {
    const playedUrls: string[] = []

    const controller = new AbortController()
    const items = [
      { url: 'test1.mp3', rate: 1.0 },
      { url: 'test2.mp3', rate: 1.0 },
    ]

    // Override play to track which URLs are played
    const originalPlay_ = player.play.bind(player)
    player.play = ((url: string, rate: number, onTime?: (t: number) => void) => {
      playedUrls.push(url)
      return originalPlay_(url, rate, onTime)
    }) as typeof player.play

    const sequence = playSequence(player, items, 100, controller.signal)

    // Let first play start
    await Promise.resolve()

    // Abort during first play
    controller.abort()
    await sequence

    // Only first item should have been played
    expect(playedUrls).toEqual(['test1.mp3'])
  })

  const flush = async () => { for (let i = 0; i < 5; i++) await Promise.resolve() }
  const elFor = (url: string) =>
    Array.from(audioElements.entries()).find(([, v]) => v.url === url)![0]
  const finish = (url: string) => {
    const el = elFor(url)
    audioElements.get(el)!.ended = true
    el.dispatchEvent(new Event('ended'))
  }

  // Runs a two-item sequence to natural completion with a signal, returning
  // the signal plus add/remove listener spies.
  async function runToCompletion() {
    vi.useFakeTimers()
    const controller = new AbortController()
    const signal = controller.signal
    const addSpy = vi.spyOn(signal, 'addEventListener')
    const removeSpy = vi.spyOn(signal, 'removeEventListener')
    const seq = playSequence(
      player,
      [{ url: 'a.mp3', rate: 1.0 }, { url: 'b.mp3', rate: 1.0 }],
      100,
      signal
    )
    await flush()
    finish('a.mp3')
    await vi.advanceTimersByTimeAsync(100)
    finish('b.mp3')
    await vi.advanceTimersByTimeAsync(100)
    await seq
    return { controller, addSpy, removeSpy }
  }

  it('natural finish unaffected by later abort: unrelated play keeps running', async () => {
    const { controller } = await runToCompletion()

    const other = player.play('other.mp3', 1.0)
    let otherSettled = false
    other.then(() => { otherSettled = true }, () => { otherSettled = true })
    await flush()
    const otherEl = elFor('other.mp3')
    const pauseMock = HTMLMediaElement.prototype.pause as ReturnType<typeof vi.fn>
    pauseMock.mockClear()

    controller.abort()
    await flush()

    expect(otherSettled).toBe(false)
    expect(player['current']).toBe(otherEl)
    expect(pauseMock).not.toHaveBeenCalled()

    player.stop()
    await other
  })

  it('removes every abort listener it added once the sequence completes naturally', async () => {
    const { addSpy, removeSpy } = await runToCompletion()
    const added = addSpy.mock.calls.filter((c) => c[0] === 'abort').map((c) => c[1])
    const removed = removeSpy.mock.calls.filter((c) => c[0] === 'abort').map((c) => c[1])
    // 2 play-phase + 2 gap-phase listeners
    expect(added.length).toBe(4)
    for (const h of added) expect(removed).toContain(h)
  })

  it('gap-phase abort listener is removed when the gap timer fires first', async () => {
    vi.useFakeTimers()
    const controller = new AbortController()
    const signal = controller.signal
    const seq = playSequence(player, [{ url: 'a.mp3', rate: 1.0 }], 100, signal)
    await flush()
    finish('a.mp3')
    await flush() // play phase done, now in gap phase

    const removeSpy = vi.spyOn(signal, 'removeEventListener')
    await vi.advanceTimersByTimeAsync(100)
    await seq

    const clearSpy = vi.spyOn(globalThis, 'clearTimeout')
    controller.abort()
    // a leaked gap listener would call clearTimeout on abort
    expect(clearSpy).not.toHaveBeenCalled()
    expect(removeSpy.mock.calls.some((c) => c[0] === 'abort')).toBe(true)
    clearSpy.mockRestore()
  })

  it("calls each item's onStart just before it plays, in order, and none after an abort", async () => {
    const events: string[] = []
    const controller = new AbortController()
    vi.spyOn(player, 'play').mockImplementation(async (url: string) => {
      events.push(`play ${url}`)
      if (url === 'b.mp3') controller.abort()
    })
    vi.useFakeTimers()
    const seq = playSequence(player, [
      { url: 'a.mp3', rate: 1, onStart: () => events.push('start a') },
      { url: 'b.mp3', rate: 1, onStart: () => events.push('start b') },
      { url: 'c.mp3', rate: 1, onStart: () => events.push('start c') },
    ], 100, controller.signal)
    await vi.advanceTimersByTimeAsync(300)
    await seq
    expect(events).toEqual(['start a', 'play a.mp3', 'start b', 'play b.mp3'])
  })

  it('a sequence item with from/to plays that range of its clip', async () => {
    const range = vi.spyOn(player, 'playRange').mockResolvedValue()
    const play = vi.spyOn(player, 'play').mockResolvedValue()
    const onTime = vi.fn()
    vi.useFakeTimers()
    const seq = playSequence(player, [{ url: 'ref.mp3', rate: 0.75 }, { url: 'you.wav', rate: 1, from: 0.4, to: 1.3, onTime }], 100)
    await vi.advanceTimersByTimeAsync(300)
    await seq
    expect(play).toHaveBeenCalledTimes(1)
    expect(play).toHaveBeenCalledWith('ref.mp3', 0.75, undefined)
    expect(range).toHaveBeenCalledWith('you.wav', 1, 0.4, 1.3, onTime)
  })

  describe('playRange', () => {
    const flushRaf = () => { for (const item of rafQueue.splice(0)) item.callback(0) }
    const pauseMock = () => HTMLMediaElement.prototype.pause as ReturnType<typeof vi.fn>
    const settledFlag = (p: Promise<void>) => { const f = { done: false }; p.then(() => { f.done = true }, () => { f.done = true }); return f }

    it('seeks to fromS, applies the rate, and pauses and resolves at toS', async () => {
      const onTime = vi.fn()
      const p = player.playRange('r.wav', 0.75, 1.2, 1.5, onTime)
      const settled = settledFlag(p)
      await flush()
      const el = elFor('r.wav')
      expect(el.currentTime).toBeCloseTo(1.2, 5)
      expect(el.playbackRate).toBe(0.75)
      flushRaf()
      expect(onTime).toHaveBeenLastCalledWith(1.2)
      await flush()
      expect(settled.done).toBe(false)

      el.currentTime = 1.51
      pauseMock().mockClear()
      flushRaf()
      await p
      expect(pauseMock()).toHaveBeenCalled()
      expect(onTime).toHaveBeenLastCalledWith(1.5)
      expect(player['current']).toBeNull()
      expect(rafQueue.length).toBe(0)
    })

    it('watches for the range end even without an onTime callback', async () => {
      const p = player.playRange('r.wav', 1, 0.5, 0.8)
      await flush()
      expect(rafQueue.length).toBe(1)
      elFor('r.wav').currentTime = 0.8
      flushRaf()
      await p
      expect(rafQueue.length).toBe(0)
    })

    it('stop() settles the range and nothing fires afterwards', async () => {
      const onTime = vi.fn()
      const p = player.playRange('r.wav', 1, 1, 1.5, onTime)
      await flush()
      flushRaf()
      const calls = onTime.mock.calls.length
      player.stop()
      await p
      const el = elFor('r.wav')
      el.currentTime = 2
      pauseMock().mockClear()
      flushRaf()
      expect(onTime.mock.calls.length).toBe(calls)
      expect(pauseMock()).not.toHaveBeenCalled()
    })

    it('a new play() of the same url cancels the range; the old range end does not pause it', async () => {
      const onRange = vi.fn()
      const p1 = player.playRange('r.wav', 1, 1, 1.5, onRange)
      await flush()
      flushRaf()
      const rangeCalls = onRange.mock.calls.length
      const onPlay = vi.fn()
      const p2 = player.play('r.wav', 1, onPlay)
      const settled2 = settledFlag(p2)
      await p1
      await flush()
      const el = elFor('r.wav')
      expect(el.currentTime).toBe(0)
      el.currentTime = 1.6 // past the old range end
      pauseMock().mockClear()
      flushRaf()
      await flush()
      expect(pauseMock()).not.toHaveBeenCalled()
      expect(onRange.mock.calls.length).toBe(rangeCalls)
      expect(onPlay).toHaveBeenLastCalledWith(1.6)
      expect(settled2.done).toBe(false)
      expect(player['current']).toBe(el)
      player.stop()
      await p2
    })

    it('a range cancels a pending play()', async () => {
      const p1 = player.play('a.mp3', 1)
      await flush()
      const p2 = player.playRange('a.mp3', 1, 0.2, 0.4)
      await p1
      expect(player['current']).toBe(elFor('a.mp3'))
      player.stop()
      await p2
    })

    it('resolves on natural end when the file ends before toS', async () => {
      const p = player.playRange('r.wav', 1, 1, 99)
      await flush()
      finish('r.wav')
      await p
      expect(player['current']).toBeNull()
      expect(rafQueue.length).toBe(0)
    })
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

  it('plays every clip at the set volume and changes the one playing at once', async () => {
    player.setVolume(0.4)
    const p = player.play('vol.mp3', 1)
    await Promise.resolve()
    const a = [...audioElements.keys()].find((el) => audioElements.get(el)?.url === 'vol.mp3')!
    expect(a.volume).toBeCloseTo(0.4)
    player.setVolume(1.5)
    expect(a.volume).toBe(1)
    player.stop(); await p
  })

  it('applies the volume to a cached element and to a range play', async () => {
    const p1 = player.play('vol2.mp3', 1)
    await Promise.resolve()
    player.stop(); await p1
    player.setVolume(0.3)
    const p2 = player.playRange('vol2.mp3', 1, 0.5, 1)
    await Promise.resolve()
    const a = [...audioElements.keys()].find((el) => audioElements.get(el)?.url === 'vol2.mp3')!
    expect(a.volume).toBeCloseTo(0.3)
    player.stop(); await p2
  })
})
