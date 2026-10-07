import { describe, expect, it } from 'vitest'
import { cueFor, cuePhase, type PageActivity } from './cue'

describe('cueFor', () => {
  it.each([
    ['echo', 'ready', '⏸', 'Ready — Enter to start', 'neutral'],
    ['echo', 'listen', '🎧', 'Listen', 'ref'],
    ['echo', 'speak', '🗣', 'Your turn — speak now', 'you'],
    ['echo', 'review', '🎧', 'Listen — the original, then you', 'ref'],
    ['echo', 'done', '✓', 'Done — → for the next sentence, Enter to try again', 'ok'],
    ['chorus', 'ready', '⏸', 'Ready — Enter to start', 'neutral'],
    ['chorus', 'listen', '🎧', 'Listen', 'ref'],
    ['chorus', 'along', '🎤', 'Speak along', 'you'],
    ['chorus', 'review', '🎧', 'Listen — the original, then you', 'ref'],
    ['chorus', 'done', '✓', 'Done — → for the next sentence, Enter to try again', 'ok'],
    ['flow', 'ready', '⏸', 'Ready — Enter to start', 'neutral'],
    ['flow', 'listen', '🎧', 'Listen', 'ref'],
    ['flow', 'speak', '🗣', 'Your turn — speak now', 'you'],
    ['flow', 'along', '🎤', 'Speak along', 'you'],
    ['flow', 'done', '✓', 'Done — Enter to run it again', 'ok'],
    ['guided', 'listen', '🎧', 'Listen', 'ref'],
    ['guided', 'along', '🎤', 'Whisper along', 'you'],
    ['guided', 'speak', '🗣', 'Your turn — say it without the text', 'you'],
    ['guided', 'review', '🎧', 'Listen — the original, then you', 'ref'],
  ] as const)('%s / %s', (mode, phase, icon, text, tone) => {
    expect(cueFor(mode, { phase })).toEqual({ icon, text, tone })
  })
  it('Guided ready names the step Enter starts', () => {
    expect(cueFor('guided', { phase: 'ready', guided: 'listen' }).text).toBe('Ready — Enter to listen')
    expect(cueFor('guided', { phase: 'ready', guided: 'whisper' }).text).toBe('Ready — Enter, then whisper along')
    expect(cueFor('guided', { phase: 'ready', guided: 'record' }).text).toBe('Ready — Enter, then say it without the text')
  })
  it('an error turns the cue red in every mode', () => {
    for (const m of ['echo', 'chorus', 'flow', 'guided'] as const) {
      expect(cueFor(m, { phase: 'listen', error: true })).toEqual({ icon: '⚠', text: 'Something went wrong — see the message below', tone: 'bad' })
    }
  })
})

describe('cuePhase', () => {
  const base: PageActivity = { mode: 'echo', echo: 'idle', runKind: null, guided: 'listen', hasTake: false, flowPhase: 'setup', flowSub: 'after', flowTurn: false }
  it.each([
    [{}, 'ready'],
    [{ hasTake: true }, 'done'],
    [{ echo: 'playing' }, 'listen'],
    [{ echo: 'recording' }, 'speak'],
    [{ echo: 'uploading' }, 'review'],
    [{ echo: 'playback' }, 'review'],
    [{ mode: 'chorus', runKind: 'chorus', echo: 'recording' }, 'along'],
    [{ mode: 'guided', runKind: 'guided', guided: 'listen' }, 'listen'],
    [{ mode: 'guided', runKind: 'guided', guided: 'whisper' }, 'along'],
    [{ mode: 'guided', echo: 'recording', guided: 'record' }, 'speak'],
    [{ mode: 'guided', hasTake: true }, 'ready'],
    [{ mode: 'flow', flowPhase: 'running', flowSub: 'after' }, 'listen'],
    [{ mode: 'flow', flowPhase: 'running', flowSub: 'after', flowTurn: true }, 'speak'],
    [{ mode: 'flow', flowPhase: 'running', flowSub: 'along' }, 'along'],
    [{ mode: 'flow', flowPhase: 'summary' }, 'done'],
    [{ mode: 'flow', hasTake: true }, 'ready'],
  ] as const)('%o → %s', (over, want) => {
    expect(cuePhase({ ...base, ...over } as PageActivity)).toBe(want)
  })
})
