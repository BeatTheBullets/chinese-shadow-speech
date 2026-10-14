import type { Mode } from '../api/types'

export const MODES: Mode[] = ['echo', 'chorus', 'flow', 'guided']
export const modeName = (m: Mode): string => m[0].toUpperCase() + m.slice(1)

// Hover text on each mode tab and the help overlay (addendum §6.1).
export function modeHelp(m: Mode, chorusPasses: number): string {
  switch (m) {
    case 'echo': return 'One sentence at a time: listen, then repeat it on your own. You hear the original and your take back to back.'
    case 'chorus': return `Speak at the same time as the sentence, ${chorusPasses} times in a row. Only the last pass is recorded.`
    case 'flow': return 'Shadow a whole passage without stopping. After: each sentence plays, then you repeat it in the pause. Along: speak at the same time as the audio (use headphones).'
    case 'guided': return 'Four steps per sentence: listen → whisper along with the text → say it with the text hidden → next.'
    case 'drill': return 'Targeted practice on your weakest tones: listen, record, retry until the target syllables are green.'
  }
}

export const KEY_HELP: [string, string][] = [
  ['Space', 'Play the sentence'], ['Enter', 'Start or stop: record (Echo), Chorus, Flow, the next Guided step'],
  ['C', 'Chorus'], ['← →', 'Previous / next sentence'], ['R', 'Replay your take'], ['S', '0.75× speed'],
  ['T  P  E', 'Hanzi, pinyin, translation'], ['F', 'Flag the sentence'], ['A', 'Send to Anki'], ['L', 'Lesson list'], ['?', 'This help'],
]
