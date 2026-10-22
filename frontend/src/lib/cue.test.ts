import { describe, expect, it } from 'vitest'
import { stageOf, type PageActivity } from './cue'

const base: PageActivity = { mode: 'echo', echo: 'idle', runKind: null, flowPhase: 'setup', flowSub: 'after', flowTurn: false }

describe('stageOf', () => {
  it.each([
    [{}, 'idle'],
    [{ echo: 'playing' }, 'listen'],
    [{ echo: 'recording' }, 'yourTurn'],
    [{ echo: 'uploading' }, 'review'],
    [{ echo: 'playback' }, 'review'],
    [{ mode: 'flow', flowPhase: 'running', flowSub: 'after' }, 'listen'],
    [{ mode: 'flow', flowPhase: 'running', flowSub: 'after', flowTurn: true }, 'yourTurn'],
    [{ mode: 'flow', flowPhase: 'running', flowSub: 'along' }, 'along'],
    [{ mode: 'flow', flowPhase: 'summary' }, 'idle'],
    [{ mode: 'flow', echo: 'playing' }, 'listen'],                       // Space plays the sentence in the setup
    [{ mode: 'flow', flowPhase: 'summary', echo: 'playing' }, 'listen'], // … and under the summary
    [{ mode: 'flow', flowPhase: 'running', flowSub: 'along', echo: 'playing' }, 'along'], // a run's own stage wins
  ] as const)('%o → %s', (over, want) => {
    expect(stageOf({ ...base, ...over } as PageActivity)).toBe(want)
  })
})
