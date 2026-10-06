import { playClip, sleep } from '../audio/abortable'
import type { ClipPlayer } from '../audio/player'
import { gapAfter, type ActualPlay, type FlowSub } from './flow'

// Extra pause after an `after` gap so the slice (gap + 150 ms slack) ends before the next clip starts.
export const AFTER_PAUSE_MS = 300

export interface FlowClip { segmentId: number; idx: number; url: string; duration: number }
export interface PlayFlowOptions {
  player: Pick<ClipPlayer, 'play' | 'stop' | 'preload'>
  clock: () => number            // the recorder's clock (AudioContext.currentTime)
  clips: FlowClip[]
  sub: FlowSub
  gapFactor: number
  rate: () => number             // read per clip, so a speed change applies from the next sentence
  signal: AbortSignal            // stop: finished sentences keep their stamps, the one in progress is dropped
  onClip: (clip: FlowClip, skip: AbortController) => void // the sentence now playing; abort `skip` to drop it and move on
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
    try {
      await playClip(o.player, c.url, rate, skip.signal)
      if (skip.signal.aborted) { if (!o.signal.aborted) skipped++; continue }
      a.playEnd = o.clock()
      if (o.sub === 'after') {
        await sleep(gapAfter(a.refDuration, o.gapFactor) * 1000 + AFTER_PAUSE_MS, skip.signal)
        if (skip.signal.aborted && !o.signal.aborted) { delete a.playEnd; skipped++ } // skipped during its gap
      }
    } catch (error) {
      return { actual, skipped, error }
    } finally {
      o.signal.removeEventListener('abort', onStop)
    }
  }
  return { actual, skipped, error: null }
}
