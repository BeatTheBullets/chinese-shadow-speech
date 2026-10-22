import type { AlignSpan, Segment } from '../api/types'
import type { FlowSub } from './flow'
import { isPunct } from './text'

// Karaoke cues (addendum §6.5): all the timing logic, so the components only draw.

export interface ClipSpan { start: number; end: number }          // clip-relative seconds, one per speech character
export interface Wipe { tone: 'ref' | 'ghost'; progress: number } // progress: speech characters coloured, 0 … n
export interface CountIn { start: number; end: number }

export const COUNT_IN_S = 1.5
export const MIN_COUNT_IN_GAP_S = 0.5

// ref_alignment_json is source-absolute; the clip starts at the segment's start_s.
export function clipSpans(spans: AlignSpan[] | null | undefined, clipStart: number): ClipSpan[] {
  return (spans ?? []).map((s) => ({ start: s.start - clipStart, end: s.end - clipStart }))
}

// Speech characters coloured at clip time `t`: those whose span has ended plus the fraction of the one in progress.
// It holds between characters, and a zero-length span counts as soon as it is reached.
export function wipeProgress(spans: ClipSpan[] | null | undefined, t: number): number {
  let p = 0
  for (const s of spans ?? []) {
    if (t >= s.end) { p += 1; continue }
    if (t > s.start) p += (t - s.start) / (s.end - s.start)
    break
  }
  return p
}

// The ghost wipe: the reference's pace replayed from the start of the learner's turn (`elapsed` seconds ago), slowed
// with the playback rate (at 0.75× the learner gets 1 / 0.75 as long).
export function ghostProgress(spans: ClipSpan[] | null | undefined, elapsed: number, rate: number): number {
  return spans?.length ? wipeProgress(spans, spans[0].start + elapsed * rate) : 0
}

// The 1.5 s before the learner must start at `startAt` (any clock, seconds); null when the gap before that moment is
// under 0.5 s (no room to count in: the learner is still speaking the previous line).
export function countInWindow(startAt: number, gapBefore: number): CountIn | null {
  return gapBefore < MIN_COUNT_IN_GAP_S ? null : { start: startAt - COUNT_IN_S, end: startAt }
}

// The countdown number at time `t` (spec §3, the 3 · 2 · 1 ring): each a third of the window, null outside it.
export function countIn(w: CountIn | null, t: number): 3 | 2 | 1 | null {
  if (!w || t < w.start || t >= w.end) return null
  return Math.min(3, Math.ceil((3 * (w.end - t)) / (w.end - w.start))) as 3 | 2 | 1
}

// Per character (code point) of `text`: how much of it the wipe covers (0 … 1) when `progress` speech characters are
// coloured. Punctuation is coloured together with the speech character before it.
export function charFill(text: string, progress: number): number[] {
  const out: number[] = []
  let k = 0, last = 0
  for (const ch of text) {
    if (isPunct(ch)) { out.push(last >= 1 ? 1 : 0); continue }
    last = Math.max(0, Math.min(1, progress - k))
    out.push(last)
    k++
  }
  return out
}

type SegTiming = Pick<Segment, 'start_s' | 'end_s' | 'ref_alignment_json'>
// Flow along: when the next line's speech starts (real seconds from the start of the current clip) and the silence
// before it (real seconds), from the alignment when there is one, else from the clip bounds.
export function nextLineStart(cur: SegTiming, next: SegTiming, rate: number): { at: number; gap: number } {
  const al = cur.ref_alignment_json ?? []
  const curSpeechEnd = al.length ? al[al.length - 1].end : cur.end_s
  const lead = (next.ref_alignment_json?.[0]?.start ?? next.start_s) - next.start_s
  return { at: (cur.end_s - cur.start_s + lead) / rate, gap: (cur.end_s - curSpeechEnd + lead) / rate }
}

// Flow along: when the line `cur` speaks within its own clip (real seconds from its start) and the silence before it
// after `prev`, so the count-in begun on the previous clip carries on through this clip's lead silence.
export function lineLead(prev: SegTiming, cur: SegTiming, rate: number): { at: number; gap: number } {
  const { at, gap } = nextLineStart(prev, cur, rate)
  return { at: at - (prev.end_s - prev.start_s) / rate, gap }
}

export interface StageWipeInput {
  spans: ClipSpan[] | null | undefined; refPlaying: boolean; refHead: number | null
  turnStart: number | null // performance-clock second an Echo take began, else null
  now: number; rate: number
}
// Echo and Drill: the colour wipe while the reference plays; for an Echo take, the ghost wipe from 1.5 s after the
// moment it starts recording. Echo has no countdown (spec §8): its old count-in dots are gone, the ghost's delay stays.
export function stageWipe(i: StageWipeInput): { wipe: Wipe | null } {
  if (i.turnStart != null) {
    const elapsed = i.now - (i.turnStart + COUNT_IN_S)
    return { wipe: elapsed >= 0 && i.spans?.length ? { tone: 'ghost', progress: ghostProgress(i.spans, elapsed, i.rate) } : null }
  }
  if (i.refPlaying && i.spans?.length) return { wipe: { tone: 'ref', progress: wipeProgress(i.spans, i.refHead ?? 0) } }
  return { wipe: null }
}

export interface FlowWipeInput {
  spans: ClipSpan[] | null | undefined; sub: FlowSub
  clipTime: number | null; clipDuration: number                    // media seconds of the current clip
  turn: { startedAt: number; duration: number } | null              // after: the speaking window (performance clock)
  now: number; rate: number
  next: { at: number; gap: number } | null                          // along: nextLineStart() of the next line
  lead?: { at: number; gap: number } | null                         // along: lineLead() of this line, after the one before it in the run
}
// Flow: the colour wipe while a clip plays, the 3 · 2 · 1 countdown before the learner's turn (after: the clip's last
// 1.5 s; along: before each new line, from the end of the clip before it on through its own lead silence), and in
// after's turn the ghost wipe and the share of the turn left (turn bar).
export function flowWipe(i: FlowWipeInput): { wipe: Wipe | null; count: 3 | 2 | 1 | null; turnLeft: number | null } {
  if (i.turn) {
    const elapsed = Math.max(0, i.now - i.turn.startedAt)
    return {
      wipe: i.spans?.length ? { tone: 'ghost', progress: ghostProgress(i.spans, elapsed, i.rate) } : null,
      count: null, turnLeft: i.turn.duration > 0 ? Math.max(0, 1 - elapsed / i.turn.duration) : 0,
    }
  }
  if (i.clipTime == null) return { wipe: null, count: null, turnLeft: null }
  const t = i.clipTime / i.rate
  const w = i.sub === 'after' ? countInWindow(i.clipDuration / i.rate, Infinity)
    : i.lead && t < i.lead.at ? countInWindow(i.lead.at, i.lead.gap)
    : i.next ? countInWindow(i.next.at, i.next.gap) : null
  return {
    wipe: i.spans?.length ? { tone: 'ref', progress: wipeProgress(i.spans, i.clipTime) } : null,
    count: countIn(w, t), turnLeft: null,
  }
}
