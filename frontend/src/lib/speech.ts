// Where the voice is in a take, from the waveform peaks already drawn for the You track (`buckets` peaks spread
// evenly over `duration` seconds): playback starts there instead of at the silence before it (Task 14). The voice
// runs from the first to the last bucket within `relDb` of the loudest one, padded by `padS` each side and clamped
// to the take. Null when there is nothing to go by (no peaks, or all silent): then the whole take plays.
export function speechBounds(peaks: Float32Array, duration: number, opts: { relDb?: number; padS?: number } = {}): { from: number; to: number } | null {
  const { relDb = -35, padS = 0.15 } = opts
  const n = peaks.length
  let max = 0
  for (const p of peaks) max = Math.max(max, p)
  if (n === 0 || !(max > 0) || !(duration > 0)) return null
  const floor = max * 10 ** (relDb / 20)
  let first = 0, last = n - 1
  while (peaks[first] <= floor) first++
  while (peaks[last] <= floor) last--
  const dt = duration / n
  return { from: Math.max(0, first * dt - padS), to: Math.min(duration, (last + 1) * dt + padS) }
}
