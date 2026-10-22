import type { Mode } from '../api/types'
import type { EchoState } from './echo'
import type { FlowSub } from './flow'

// What the whole stage shows (spec §3): listening, the 3 · 2 · 1 countdown (Flow only, set by the countdown itself),
// the learner's turn, speaking along (Flow along), the take's review playback, or nothing going on.
export type Stage = 'idle' | 'listen' | 'getReady' | 'yourTurn' | 'review' | 'along'

export interface PageActivity {
  mode: Mode; echo: EchoState; runKind: 'flow' | null; hasTake: boolean
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

// The small note on an idle stage, naming the real keys: Echo's "done" (→ moves on, Enter records again), Flow's
// Enter runs the range again. Any other stage speaks for itself.
export function idleNote(a: PageActivity): string | undefined {
  if (stageOf(a) !== 'idle') return undefined
  if (a.mode === 'flow') return a.flowPhase === 'summary' ? 'Done — Enter to run it again' : 'Ready — Enter to start'
  return a.hasTake ? 'Done — → for the next sentence, Enter to try again' : 'Ready — Enter to start'
}
