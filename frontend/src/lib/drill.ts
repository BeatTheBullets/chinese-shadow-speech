import type { Score } from '../api/types'

// One drill session's walk through its queue: listen to the reference, record, review the scored take, then either
// retry the same sentence or move on. Pure state transitions; the page owns the audio and the network.
export type DrillStep = 'listen' | 'record' | 'review' | 'done'
export type Outcome = 'retry' | 'next'
export interface DrillState { i: number; n: number; step: DrillStep; tries: number; outcome: Outcome | null }

export const startDrill = (n: number): DrillState => ({ i: 0, n, step: n > 0 ? 'listen' : 'done', tries: 0, outcome: null })

export const listened = (s: DrillState): DrillState => ({ ...s, step: 'record' })

// A gate-warning take (too quiet, no speech) was not scored: it costs no try and always offers a retry.
export function scored(s: DrillState, r: { gated: boolean; allGreen: boolean }, maxTries: number): DrillState {
  if (r.gated) return { ...s, step: 'review', outcome: 'retry' }
  const tries = s.tries + 1
  return { ...s, step: 'review', tries, outcome: r.allGreen || tries >= maxTries ? 'next' : 'retry' }
}

export const skip = (s: DrillState): DrillState =>
  s.i + 1 >= s.n ? { ...s, step: 'done', outcome: null } : { ...s, i: s.i + 1, step: 'listen', tries: 0, outcome: null }

export const advance = (s: DrillState): DrillState =>
  s.outcome === 'retry' ? { ...s, step: 'record', outcome: null } : skip(s)

// Green = every target syllable came out `ok`. An unscored take (overall null) or a stale index never counts.
export function targetsGreen(score: Score | null | undefined, targets: number[]): boolean {
  if (score?.overall == null) return false
  return targets.every((t) => score.syllables[t]?.status === 'ok')
}
