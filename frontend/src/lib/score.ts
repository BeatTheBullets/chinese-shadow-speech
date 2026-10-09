import type { Score, Segment } from '../api/types'
import type { Cell } from './cells'

export const TONE_NAMES: Record<number, string> = { 0: 'neutral', 1: 'high', 2: 'rising', 3: 'low', 4: 'falling' }
const WARNINGS: Record<string, string> = {
  too_short: 'Too short — not scored. Say the whole sentence.',
  too_quiet: 'Too quiet — not scored. Move closer to the mic.',
  clipped: 'Too loud — not scored. Lower the mic gain.',
  wrong_or_unclear: 'Could not match this to the sentence — not scored.',
  no_voice: 'No voice found — not scored.',
  no_tone_model: 'Tone model missing — not scored. See docs/running.md.',
  no_reference: 'This sentence has no reference timing — not scored.',
  align_failed: 'Could not align this take — not scored.',
  score_failed: 'Scoring failed — the take is saved.',
}

// The You row's cells with each syllable's verdict; unchanged when there is no score or it is for other text.
export function withScore(cells: Cell[], score: Score | null | undefined): Cell[] {
  const syl = score?.syllables
  if (!syl?.length || syl.length !== cells.length) return cells
  return cells.map((c, i) => ({ ...c, status: syl[i].status, score: syl[i].tone_score, target: syl[i].target_tone, heard: syl[i].heard_tone }))
}

export function warningText(score: Score | null | undefined): string | null {
  const w = score?.overall == null ? score?.warnings?.[0] : undefined
  return w ? WARNINGS[w] ?? `Not scored (${w}).` : null
}

export const pct = (x: number | null | undefined): string => (x == null ? '—' : String(Math.round(x * 100)))

export function cellTitle(c: Cell): string {
  if (c.target == null || c.heard == null) return c.pinyin
  return `${c.pinyin} · Speaker: tone ${c.target} (${TONE_NAMES[c.target]}) · You: tone ${c.heard} (${TONE_NAMES[c.heard]}) · ${pct(c.score)}`
}

// The sentence after one more attempt, as the lessons API would now report it (last/best of scored takes only).
export function applyAttempt(seg: Segment, overall: number | null | undefined): Segment {
  if (overall == null) return { ...seg, attempts: seg.attempts + 1 }
  return { ...seg, attempts: seg.attempts + 1, last_score: overall, best_score: Math.max(seg.best_score ?? overall, overall) }
}
