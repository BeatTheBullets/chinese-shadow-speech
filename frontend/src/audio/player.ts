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

export class ClipPlayer {
  private els = new Map<string, HTMLAudioElement>()
  private current: HTMLAudioElement | null = null
  private ctx: AudioContext | null = null
  private peakCache = new Map<string, Float32Array>()

  private el(url: string): HTMLAudioElement {
    let a = this.els.get(url)
    if (!a) { a = new Audio(url); a.preload = 'auto'; (a as any).preservesPitch = true; this.els.set(url, a) }
    return a
  }
  async preload(url: string) { const a = this.el(url); if (a.readyState < 2) await new Promise<void>((r) => { a.oncanplaythrough = () => r(); a.onerror = () => r(); a.load() }) }
  get currentTime() { return this.current?.currentTime ?? 0 }
  stop() { if (this.current) { this.current.pause(); this.current.currentTime = 0; this.current = null } }
  play(url: string, rate: number, onTime?: (t: number) => void): Promise<void> {
    this.stop()
    const a = this.el(url); this.current = a; a.playbackRate = rate; a.currentTime = 0
    return new Promise((resolve, reject) => {
      let raf = 0
      const tick = () => { onTime?.(a.currentTime); raf = requestAnimationFrame(tick) }
      a.onended = () => { cancelAnimationFrame(raf); onTime?.(a.duration); if (this.current === a) this.current = null; resolve() }
      a.onerror = () => { cancelAnimationFrame(raf); reject(new Error('audio error')) }
      a.play().then(() => { if (onTime) raf = requestAnimationFrame(tick) }).catch(reject)
    })
  }
  async peaksFor(url: string, buckets: number): Promise<Float32Array> {
    const key = `${url}#${buckets}`
    const hit = this.peakCache.get(key); if (hit) return hit
    this.ctx ??= new AudioContext()
    const buf = await this.ctx.decodeAudioData(await (await fetch(url)).arrayBuffer())
    const p = peaks(buf.getChannelData(0), buckets); this.peakCache.set(key, p); return p
  }
}

export async function playSequence(player: ClipPlayer, items: { url: string; rate: number; onTime?: (t: number) => void }[], gapMs = 250) {
  for (const it of items) { await player.play(it.url, it.rate, it.onTime); await new Promise((r) => setTimeout(r, gapMs)) }
}
