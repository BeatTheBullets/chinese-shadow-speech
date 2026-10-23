import type { Mode } from '../api/types'
import type { EchoState } from './echo'
import type { FlowSub } from './flow'

// What the whole stage shows (spec §3): listening, the 3 · 2 · 1 countdown (Flow only, set by the countdown itself),
// the learner's turn, speaking along (Flow along), the take's review playback, a stored Flow run playing back
// (replay, set by the page while it plays), or nothing going on.
export type Stage = 'idle' | 'listen' | 'getReady' | 'yourTurn' | 'review' | 'along' | 'replay'

export interface PageActivity {
  mode: Mode; echo: EchoState; runKind: 'flow' | null
  flowPhase: 'setup' | 'running' | 'summary'; flowSub: FlowSub; flowTurn: boolean // flowTurn: Flow after's speaking window is open
}

// The stage from the practice page's state. Flow's getReady is not here: FlowView sets it while countIn() counts.
export function stageOf(a: PageActivity): Stage {
  if (a.mode === 'flow') {
    if (a.flowPhase === 'running') return a.flowSub === 'along' ? 'along' : a.flowTurn ? 'yourTurn' : 'listen'
    return a.echo === 'playing' ? 'listen' : 'idle'   // setup or summary: Space still plays the sentence
  }
  if (a.echo === 'recording') return 'yourTurn'
  if (a.echo === 'playing') return 'listen'
  if (a.echo === 'playback' || a.echo === 'uploading') return 'review'
  return 'idle'
}
