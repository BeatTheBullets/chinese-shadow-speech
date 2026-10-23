import type { AlignSpan } from '../api/types'
import { speechBounds } from './speech'

// The Echo review's time axis: each track is trimmed to its voice and both share one scale (TwoTrack), so the longer
// voice fills the box and the shorter keeps its true relative length — timing stays comparable at a glance.

// Room left either side of the voice, so a soft onset or a trailing breath is not cut off at the box edge.
export const SPEECH_MARGIN_S = 0.1

// The scorer's window tail, mirroring TAIL in backend shadow/scoring/windows.py: aligner (CTC) spans stop about half-way
// through a syllable, so a syllable followed by a pause, or the last one, is taken to run this far past its span end.
export const SPAN_TAIL_S = 0.15

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

// The reference's window, measured as your take's is so equal speech gives equal lengths on the shared scale: when
// scored, the score's reference windows (ref_contour.spans, windows() output like usr_contour's); before that, the
// alignment (source-absolute, so less the clip start) with its last end extended by the scorer's tail, the same rule
// windows() applies to the last syllable; without alignment, the peaks.
export function refWindow(duration: number, alignment: AlignSpan[] | null | undefined, clipStart: number, scored: [number, number][] | null | undefined, peaks: Float32Array | null): SpeechWindow | null {
  if (scored?.length) return speechWindow(duration, scored)
  const spans = (alignment ?? []).map((s) => [s.start - clipStart, s.end - clipStart] as [number, number])
  if (spans.length) { const last = spans[spans.length - 1]; last[1] = Math.max(last[1], Math.min(duration, last[1] + SPAN_TAIL_S)) }
  return speechWindow(duration, spans, peaks)
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

// A track's bars scaled to its own loudest one (display only: scoring never sees this), so a quiet mic still draws a
// clear waveform beside a loud clip. A copy; silence (or nothing) as it is, so there is no division by zero.
export function normalizePeaks(peaks: Float32Array | null): Float32Array | null {
  if (!peaks) return null
  let max = 0
  for (const p of peaks) if (p > max) max = p
  return max > 0 ? peaks.map((p) => p / max) : peaks.slice()
}
