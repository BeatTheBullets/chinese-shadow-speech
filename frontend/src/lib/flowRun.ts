import { playClip, sleep } from '../audio/abortable'
import type { ClipPlayer } from '../audio/player'
import { gapAfter, type ActualPlay, type FlowSub } from './flow'

// Extra pause after an `after` gap so the slice (gap + 150 ms slack) ends before the next clip starts.
export const AFTER_PAUSE_MS = 300

// A clip that has not ended this long after its expected length (duration / rate) never will: its request is stuck
// (dead backend behind an open socket) and `play()` stays pending, with neither `ended` nor `error`. Covers a slow
// first-byte on a healthy server.
export const CLIP_GRACE_MS = 5000

export interface FlowClip { segmentId: number; idx: number; url: string; duration: number }
export interface PlayFlowOptions {
  player: Pick<ClipPlayer, 'play' | 'stop' | 'preload'>
  clock: () => number            // the recorder's clock (AudioContext.currentTime)
  clips: FlowClip[]
  sub: FlowSub
  gapFactor: number
  rate: () => number             // read per clip, so a speed change applies from the next sentence
  signal: AbortSignal            // stop: finished sentences keep their stamps, the one in progress (clip or after-gap) is dropped
  onClip: (clip: FlowClip, skip: AbortController) => void // the sentence now playing; abort `skip` to drop it and move on
  onTime?: (t: number) => void                                          // clip-relative time of the sentence playing (karaoke)
  onTurn?: (clip: FlowClip, turn: { duration: number } | null) => void // after: the speaking window opens (its length) / closes
}
export interface FlowPlayback { actual: ActualPlay[]; skipped: number; error: unknown }

// Plays a Flow run (§6): clips back to back (`along`) or each followed by a gap of gap_factor × the heard
// duration (`after`), stamping start and end of every clip on the recording clock for slicing.
export async function playFlow(o: PlayFlowOptions): Promise<FlowPlayback> {
  const actual: ActualPlay[] = []
  let skipped = 0
  for (let i = 0; i < o.clips.length && !o.signal.aborted; i++) {
    const c = o.clips[i], next = o.clips[i + 1]
    const skip = new AbortController()
    const onStop = () => skip.abort()
    o.signal.addEventListener('abort', onStop, { once: true })
    o.onClip(c, skip)
    if (next) void o.player.preload(next.url)
    const rate = o.rate()
    const a: ActualPlay = { segmentId: c.segmentId, idx: c.idx, playStart: o.clock(), refDuration: c.duration / rate }
    actual.push(a)
    let watchdog: ReturnType<typeof setTimeout> | undefined
    try {
      const stalled = new Promise<never>((_, reject) => {
        watchdog = setTimeout(() => {
          o.player.stop() // releases the pending playClip too, so nothing is left hanging
          reject(new Error('the clip did not load — is the backend running?'))
        }, (c.duration / rate) * 1000 + CLIP_GRACE_MS)
      })
      const played = playClip(o.player, c.url, rate, skip.signal, o.onTime)
      void stalled.catch(() => {}) // a late rejection (clip finished first) must not be unhandled
      await Promise.race([played, stalled])
      clearTimeout(watchdog)
      if (skip.signal.aborted) { if (!o.signal.aborted) skipped++; continue }
      a.playEnd = o.clock()
      if (o.sub === 'after') {
        // The turn (and its bar) lasts the speaking window; the short pause after it belongs to the next clip.
        const gap = gapAfter(a.refDuration, o.gapFactor)
        o.onTurn?.(c, { duration: gap })
        await sleep(gap * 1000, skip.signal)
        o.onTurn?.(c, null)
        await sleep(AFTER_PAUSE_MS, skip.signal)
        // Skipped or stopped during its gap: the learner may be mid-word, so the sentence is dropped like an unfinished one.
        if (skip.signal.aborted) { delete a.playEnd; if (!o.signal.aborted) skipped++ }
      }
    } catch (error) {
      return { actual, skipped, error }
    } finally {
      clearTimeout(watchdog) // finished, skipped, stopped or failed: no stray timer
      o.signal.removeEventListener('abort', onStop)
    }
  }
  return { actual, skipped, error: null }
}
