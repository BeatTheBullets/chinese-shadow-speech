import { describe, expect, it } from 'vitest'
import { idleNote, stageOf, type PageActivity } from './cue'

const base: PageActivity = { mode: 'echo', echo: 'idle', runKind: null, hasTake: false, flowPhase: 'setup', flowSub: 'after', flowTurn: false }

describe('stageOf', () => {
  it.each([
    [{}, 'idle'],
    [{ hasTake: true }, 'idle'],
    [{ echo: 'playing' }, 'listen'],
    [{ echo: 'recording' }, 'yourTurn'],
    [{ echo: 'uploading' }, 'review'],
    [{ echo: 'playback' }, 'review'],
    [{ mode: 'flow', flowPhase: 'running', flowSub: 'after' }, 'listen'],
    [{ mode: 'flow', flowPhase: 'running', flowSub: 'after', flowTurn: true }, 'yourTurn'],
    [{ mode: 'flow', flowPhase: 'running', flowSub: 'along' }, 'along'],
    [{ mode: 'flow', flowPhase: 'summary' }, 'idle'],
    [{ mode: 'flow', hasTake: true }, 'idle'],
  ] as const)('%o → %s', (over, want) => {
    expect(stageOf({ ...base, ...over } as PageActivity)).toBe(want)
  })
})

describe('idleNote', () => {
  it.each([
    [{}, 'Ready — Enter to start'],
    [{ hasTake: true }, 'Done — → for the next sentence, Enter to try again'],
    [{ mode: 'flow' }, 'Ready — Enter to start'],
    [{ mode: 'flow', hasTake: true }, 'Ready — Enter to start'],
    [{ mode: 'flow', flowPhase: 'summary' }, 'Done — Enter to run it again'],
  ] as const)('%o → %s', (over, want) => {
    expect(idleNote({ ...base, ...over } as PageActivity)).toBe(want)
  })
  it('says nothing outside the idle stage: the stage itself shows what to do', () => {
    expect(idleNote({ ...base, echo: 'recording' })).toBeUndefined()
    expect(idleNote({ ...base, mode: 'flow', flowPhase: 'running' })).toBeUndefined()
  })
})
