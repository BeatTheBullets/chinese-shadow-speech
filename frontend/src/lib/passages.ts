import type { Passage, Segment } from '../api/types'

// Passages (addendum §4): the server lists each passage's sentence ids; these helpers place sentences in them.

// The position in `passages` of the passage holding the sentence at lesson index `i`, or -1.
export function passageIndexOf(passages: Passage[], segments: Segment[], i: number): number {
  const id = segments[i]?.id
  return id == null ? -1 : passages.findIndex((p) => p.segment_ids.includes(id))
}

// First and last lesson index of the passage's sentences, or null when none of them is in `segments`.
export function passageSpan(p: Passage, segments: Segment[]): { from: number; to: number } | null {
  const idx = segments.map((s, i) => (p.segment_ids.includes(s.id) ? i : -1)).filter((i) => i >= 0)
  return idx.length ? { from: idx[0], to: idx[idx.length - 1] } : null
}

// Done: every sentence has at least one attempt, on the server or uploaded during this visit.
export function passageDone(p: Passage, segments: Segment[], practised: readonly number[]): boolean {
  const byId = new Map(segments.map((s) => [s.id, s]))
  return p.segment_ids.length > 0 && p.segment_ids.every((id) => (byId.get(id)?.attempts ?? 0) > 0 || practised.includes(id))
}

// The drawer's groups: each passage with its sentences (lesson index and sentence) in lesson order; sentences no passage
// lists (only between an edit and the next reload) go in a last group without a passage.
export function groupByPassage(segments: Segment[], passages: Passage[]): { passage: Passage | null; rows: { i: number; seg: Segment }[] }[] {
  if (!passages.length) return [{ passage: null, rows: segments.map((seg, i) => ({ i, seg })) }]
  const owner = new Map<number, number>()
  passages.forEach((p, k) => p.segment_ids.forEach((id) => owner.set(id, k)))
  const groups = passages.map((passage) => ({ passage: passage as Passage | null, rows: [] as { i: number; seg: Segment }[] }))
  const loose: { i: number; seg: Segment }[] = []
  segments.forEach((seg, i) => { const k = owner.get(seg.id); if (k == null) loose.push({ i, seg }); else groups[k].rows.push({ i, seg }) })
  return loose.length ? [...groups, { passage: null, rows: loose }] : groups
}
