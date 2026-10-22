import { describe, expect, it } from 'vitest'
import { KEY_HELP, MODES, modeHelp, modeName } from './modeHelp'

describe('mode help', () => {
  it('uses the spec texts', () => {
    expect(modeHelp('echo')).toBe('One sentence at a time: listen, then repeat it on your own. You hear the original and your take back to back.')
    expect(modeHelp('flow')).toBe('Shadow a whole passage without stopping. After: each sentence plays, then you repeat it in the pause. Along: speak at the same time as the audio (use headphones).')
  })
  it('lists Echo and Flow only, and the help key but no C', () => {
    expect(MODES.map(modeName)).toEqual(['Echo', 'Flow'])
    expect(KEY_HELP.map(([k]) => k)).toContain('?')
    expect(KEY_HELP.map(([k]) => k)).not.toContain('C')
    expect([modeName('chorus'), modeName('guided')]).toEqual(['Chorus', 'Guided']) // old attempts keep their labels
    expect(KEY_HELP.map(([, what]) => what).join(' ')).not.toMatch(/Chorus|Guided/)
  })
})
