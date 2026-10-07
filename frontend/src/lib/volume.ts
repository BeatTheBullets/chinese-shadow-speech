import type { Mode } from '../api/types'
import type { FlowSub } from './flow'

export const clamp01 = (v: number): number => (Number.isFinite(v) ? Math.max(0, Math.min(1, v)) : 0)

// Playback volume now (addendum §7): while the learner speaks along (Chorus, Flow along) the reference plays at the
// guide level of the reference volume; otherwise, and for the learner's own takes, at the reference volume.
export function playbackVolume(o: { speakingAlong: boolean; referenceVolume: number; guideLevel: number }): number {
  const ref = clamp01(o.referenceVolume)
  return o.speakingAlong ? ref * clamp01(o.guideLevel) : ref
}

// The guide-level slider is shown in these modes only.
export const guideApplies = (mode: Mode, flowSub: FlowSub): boolean => mode === 'chorus' || (mode === 'flow' && flowSub === 'along')
