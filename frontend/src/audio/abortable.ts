import type { ClipPlayer } from './player'

// Building blocks for multi-step runs (Chorus, Flow, Guided): every wait ends early when the run's signal
// aborts, and no timer or listener outlives the step.

export function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) { resolve(); return }
    const onAbort = () => { clearTimeout(timer); resolve() }
    const timer = setTimeout(() => { signal.removeEventListener('abort', onAbort); resolve() }, ms)
    signal.addEventListener('abort', onAbort, { once: true })
  })
}

// Plays one clip; aborting the signal stops the player, which settles the play.
export async function playClip(player: Pick<ClipPlayer, 'play' | 'stop'>, url: string, rate: number, signal: AbortSignal, onTime?: (t: number) => void) {
  if (signal.aborted) return
  const onAbort = () => player.stop()
  signal.addEventListener('abort', onAbort, { once: true })
  try { await player.play(url, rate, onTime) } finally { signal.removeEventListener('abort', onAbort) }
}
