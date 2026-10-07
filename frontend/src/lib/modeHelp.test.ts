import { describe, expect, it } from 'vitest'
import { KEY_HELP, MODES, modeHelp, modeName } from './modeHelp'

describe('mode help', () => {
  it('uses the spec texts, with the Chorus pass count', () => {
    expect(modeHelp('echo', 5)).toBe('One sentence at a time: listen, then repeat it on your own. You hear the original and your take back to back.')
    expect(modeHelp('chorus', 3)).toBe('Speak at the same time as the sentence, 3 times in a row. Only the last pass is recorded.')
    expect(modeHelp('flow', 5)).toBe('Shadow a whole passage without stopping. After: each sentence plays, then you repeat it in the pause. Along: speak at the same time as the audio (use headphones).')
    expect(modeHelp('guided', 5)).toBe('Four steps per sentence: listen → whisper along with the text → say it with the text hidden → next.')
  })
  it('lists every mode and the help key', () => {
    expect(MODES.map(modeName)).toEqual(['Echo', 'Chorus', 'Flow', 'Guided'])
    expect(KEY_HELP.map(([k]) => k)).toContain('?')
  })
})
