import type { Mode } from '../api/types'
import type { EchoState } from './echo'
import type { FlowSub } from './flow'
import type { GuidedStep } from './guided'

export type CueTone = 'ref' | 'you' | 'neutral' | 'ok' | 'bad'
export interface Cue { icon: string; text: string; tone: CueTone }
// What the learner should be doing right now (addendum §6.2).
export type CuePhase = 'ready' | 'listen' | 'speak' | 'along' | 'review' | 'done'
export interface CueState { phase: CuePhase; guided?: GuidedStep; error?: boolean }

const GUIDED_READY: Record<GuidedStep, string> = {
  listen: 'Ready — Enter to listen', whisper: 'Ready — Enter, then whisper along', record: 'Ready — Enter, then say it without the text',
}

// The one-line instruction above the sentence; the record button keeps only a short label. Echo and Chorus "done"
// names the real keys (→ moves on, Enter records again); Flow's Enter runs the range again.
export function cueFor(mode: Mode, s: CueState): Cue {
  if (s.error) return { icon: '⚠', text: 'Something went wrong — see the message below', tone: 'bad' }
  switch (s.phase) {
    case 'listen': return { icon: '🎧', text: 'Listen', tone: 'ref' }
    case 'speak': return { icon: '🗣', text: mode === 'guided' ? 'Your turn — say it without the text' : 'Your turn — speak now', tone: 'you' }
    case 'along': return { icon: '🎤', text: mode === 'guided' ? 'Whisper along' : 'Speak along', tone: 'you' }
    case 'review': return { icon: '🎧', text: 'Listen — the original, then you', tone: 'ref' }
    case 'done': return { icon: '✓', text: mode === 'flow' ? 'Done — Enter to run it again' : 'Done — → for the next sentence, Enter to try again', tone: 'ok' }
    case 'ready': return { icon: '⏸', text: mode === 'guided' ? GUIDED_READY[s.guided ?? 'listen'] : 'Ready — Enter to start', tone: 'neutral' }
  }
}

export interface PageActivity {
  mode: Mode; echo: EchoState; runKind: 'chorus' | 'flow' | 'guided' | null; guided: GuidedStep; hasTake: boolean
  flowPhase: 'setup' | 'running' | 'summary'; flowSub: FlowSub; flowTurn: boolean // flowTurn: Flow after's speaking window is open
}

// The cue phase from the practice page's state.
export function cuePhase(a: PageActivity): CuePhase {
  if (a.mode === 'flow') {
    if (a.flowPhase === 'running') return a.flowSub === 'along' ? 'along' : a.flowTurn ? 'speak' : 'listen'
    return a.flowPhase === 'summary' ? 'done' : 'ready'
  }
  if (a.runKind === 'chorus') return 'along'
  if (a.runKind === 'guided') return a.guided === 'whisper' ? 'along' : 'listen'
  if (a.echo === 'recording') return 'speak'
  if (a.echo === 'playing') return 'listen'
  if (a.echo === 'playback' || a.echo === 'uploading') return 'review'
  if (a.mode === 'guided') return 'ready'
  return a.hasTake ? 'done' : 'ready'
}
