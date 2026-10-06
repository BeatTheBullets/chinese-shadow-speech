export type FlowSub = 'after' | 'along'
export interface ActualPlay { segmentId: number; idx: number; playStart: number; playEnd?: number; refDuration: number }
export interface SliceRange { segmentId: number; idx: number; t0: number; t1: number }
export interface FlowResult { segmentId: number; idx: number; attemptId: number | null; url: string; duration: number }
const r3 = (x: number) => Math.round(x * 1000) / 1000
export const gapAfter = (refDuration: number, gapFactor: number) => refDuration * gapFactor
// Recording-clock windows to cut from a continuous Flow recording, one per sentence whose clip finished playing.
// An entry without playEnd (stopped or skipped mid-clip) is dropped.
export function sliceRangesFromActual(actual: ActualPlay[], sub: FlowSub, gapFactor: number, slack = 0.15): SliceRange[] {
  return actual.filter((a) => a.playEnd != null).map((a) => sub === 'after'
    ? { segmentId: a.segmentId, idx: a.idx, t0: r3(a.playEnd! - slack), t1: r3(a.playEnd! + gapAfter(a.refDuration, gapFactor) + slack) }
    : { segmentId: a.segmentId, idx: a.idx, t0: r3(a.playStart - slack), t1: r3(a.playEnd! + slack) })
}
// The n lowest-scored results, lowest first; unscored lines (all of them in Phase 1) are left out.
export function weakestResults(results: FlowResult[], scores: Map<number, number | null>, n: number): FlowResult[] {
  return results.filter((r) => scores.get(r.segmentId) != null)
    .sort((a, b) => scores.get(a.segmentId)! - scores.get(b.segmentId)!)
    .slice(0, n)
}
