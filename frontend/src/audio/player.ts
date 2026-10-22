export function peaks(samples: Float32Array, buckets: number): Float32Array {
  const out = new Float32Array(buckets)
  const per = samples.length / buckets
  for (let b = 0; b < buckets; b++) {
    const a = Math.floor(b * per), z = Math.max(a + 1, Math.floor((b + 1) * per))
    let m = 0
    for (let i = a; i < z && i < samples.length; i++) m = Math.max(m, Math.abs(samples[i]))
    out[b] = m
  }
  return out
}

type PlayToken = { cancelled: boolean; cancel?: () => void }

export class ClipPlayer {
  private els = new Map<string, HTMLAudioElement>()
  private current: HTMLAudioElement | null = null
  private ctx: AudioContext | null = null
  private peakCache = new Map<string, Float32Array>()
  private active: PlayToken | null = null
  private vol = 1

  private el(url: string): HTMLAudioElement {
    let a = this.els.get(url)
    if (!a) { a = new Audio(url); a.preload = 'auto'; a.preservesPitch = true; this.els.set(url, a) }
    return a
  }
  async preload(url: string) { const a = this.el(url); if (a.readyState < 2) await new Promise<void>((r) => { a.oncanplaythrough = () => r(); a.onerror = () => r(); a.load() }) }
  // Volume (0…1) of the clip playing and of every later one.
  setVolume(v: number) {
    this.vol = Math.max(0, Math.min(1, Number.isFinite(v) ? v : 1))
    if (this.current) this.current.volume = this.vol
  }
  get currentTime() { return this.current?.currentTime ?? 0 }
  stop() {
    if (this.active) {
      const token = this.active
      token.cancelled = true
      if (token.cancel) {
        token.cancel()
      }
    }
    if (this.current) { this.current.pause(); this.current.currentTime = 0; this.current = null }
  }
  play(url: string, rate: number, onTime?: (t: number) => void): Promise<void> {
    return this.run(url, rate, 0, null, onTime)
  }
  // Plays fromS..toS (clip-relative seconds) and pauses at toS. Same cancellation as play(): a later
  // play()/playRange()/stop() settles it, and none of its callbacks or its end-of-range pause fire afterwards.
  playRange(url: string, rate: number, fromS: number, toS: number, onTime?: (t: number) => void): Promise<void> {
    return this.run(url, rate, fromS, toS, onTime)
  }
  private run(url: string, rate: number, fromS: number, toS: number | null, onTime?: (t: number) => void): Promise<void> {
    this.stop()
    const token: PlayToken = { cancelled: false }
    this.active = token
    const a = this.el(url); this.current = a; a.playbackRate = rate; a.volume = this.vol; a.currentTime = fromS
    return new Promise((resolve, reject) => {
      let raf = 0
      const cleanup = () => { cancelAnimationFrame(raf); a.onended = null; a.onerror = null }
      const cancel = () => {
        cleanup()
        if (this.active === token) this.active = null
        resolve()
      }
      // Store cancel function so stop() can call it
      token.cancel = cancel
      // Natural end: of the file, or of the range
      const finish = (t: number) => {
        cleanup()
        onTime?.(t)
        if (this.current === a) this.current = null
        if (this.active === token) this.active = null
        resolve()
      }
      const tick = () => {
        if (token.cancelled || this.active !== token) return
        if (toS != null && a.currentTime >= toS) { a.pause(); finish(toS); return }
        onTime?.(a.currentTime)
        raf = requestAnimationFrame(tick)
      }
      a.onended = () => {
        if (token.cancelled || this.active !== token) return
        // Ignore if element hasn't actually ended (stale queued event from previous play)
        if (!a.ended) return
        finish(a.duration)
      }
      a.onerror = () => {
        if (token.cancelled || this.active !== token) return
        cleanup()
        if (this.active === token) this.active = null
        reject(new Error('audio error'))
      }
      a.play()
        .then(() => {
          if (token.cancelled || this.active !== token) return
          // A range needs the frame loop to notice its end even without onTime
          if (onTime || toS != null) raf = requestAnimationFrame(tick)
        })
        .catch((err) => {
          if (token.cancelled || this.active !== token) return
          cleanup()
          if (this.active === token) this.active = null
          reject(err)
        })
    })
  }
  async peaksFor(url: string, buckets: number): Promise<Float32Array> {
    const key = `${url}#${buckets}`
    const hit = this.peakCache.get(key); if (hit) return hit
    this.ctx ??= new AudioContext()
    const res = await fetch(url)
    if (!res.ok) throw new Error(`failed to fetch audio: ${res.status} ${res.statusText}`)
    const buf = await this.ctx.decodeAudioData(await res.arrayBuffer())
    const p = peaks(buf.getChannelData(0), buckets); this.peakCache.set(key, p); return p
  }
}

// One clip of a sequence; with `from`/`to` (clip seconds) only that range plays, e.g. a take without its silences.
export interface SequenceItem { url: string; rate: number; onTime?: (t: number) => void; from?: number; to?: number }

export async function playSequence(player: ClipPlayer, items: SequenceItem[], gapMs = 250, signal?: AbortSignal) {
  for (const it of items) {
    if (signal?.aborted) { player.stop(); return }
    const playPromise = it.from != null || it.to != null
      ? player.playRange(it.url, it.rate, it.from ?? 0, it.to ?? Infinity, it.onTime)
      : player.play(it.url, it.rate, it.onTime)
    const abortHandler = () => { player.stop() }
    const removeAbortHandler = () => { if (signal) signal.removeEventListener('abort', abortHandler) }
    try {
      if (signal) signal.addEventListener('abort', abortHandler, { once: true })
      await playPromise
    } finally {
      removeAbortHandler()
    }
    if (signal?.aborted) { player.stop(); return }
    const gapPromise = new Promise<void>((r) => {
      const timer = setTimeout(() => {
        if (signal) signal.removeEventListener('abort', gapAbortHandler)
        r()
      }, gapMs)
      const gapAbortHandler = () => { clearTimeout(timer); r() }
      if (signal) signal.addEventListener('abort', gapAbortHandler, { once: true })
    })
    await gapPromise
  }
}
