import { speechBounds } from './speech'

// The Echo review's time axis: each track is trimmed to its voice and both share one scale (TwoTrack), so the longer
// voice fills the box and the shorter keeps its true relative length — timing stays comparable at a glance.

// Room left either side of the voice, so a soft onset or a trailing breath is not cut off at the box edge.
export const SPEECH_MARGIN_S = 0.1

// A track's window on its own clip (seconds): `from` … `to` is drawn, `speech` is the voice's length without margins.
export interface SpeechWindow { from: number; to: number; speech: number }

// The voice in a clip of `duration` s, from the first span's start to the last one's end (the reference's alignment
// made clip-relative, or a scored take's usr_contour spans); without spans, from the loud `peaks` (an unscored take)
// at speechBounds' level but without its playback padding; with neither, the whole clip. Margin added, clamped to
// the clip. Null when there is no clip.
export function speechWindow(duration: number, spans: readonly (readonly [number, number])[] | null | undefined, peaks?: Float32Array | null): SpeechWindow | null {
  if (!(duration > 0)) return null
  let voice: { from: number; to: number } | null = null
  if (spans?.length) voice = { from: Math.min(...spans.map((s) => s[0])), to: Math.max(...spans.map((s) => s[1])) }
  else if (peaks) voice = speechBounds(peaks, duration, { padS: 0 })
  if (!voice || !(voice.to > voice.from)) return { from: 0, to: duration, speech: duration }
  return { from: Math.max(0, voice.from - SPEECH_MARGIN_S), to: Math.min(duration, voice.to + SPEECH_MARGIN_S), speech: voice.to - voice.from }
}

// The peaks (spread evenly over `duration`) inside the window, with the window snapped out to the edges of the
// buckets kept, so the drawn bars and everything placed by time (ticks, pitch, playhead) share one exact origin.
export function sliceToWindow(peaks: Float32Array | null, duration: number, w: SpeechWindow): { peaks: Float32Array | null; from: number; to: number } {
  if (!peaks?.length || !(duration > 0)) return { peaks, from: w.from, to: w.to }
  const dt = duration / peaks.length
  // A hair of tolerance so a window edge that is a bucket edge up to float error does not pull in a neighbour.
  const i0 = Math.max(0, Math.floor(w.from / dt + 1e-9)), i1 = Math.min(peaks.length, Math.ceil(w.to / dt - 1e-9))
  return { peaks: peaks.subarray(i0, Math.max(i0, i1)), from: i0 * dt, to: Math.max(i0, i1) * dt }
}
