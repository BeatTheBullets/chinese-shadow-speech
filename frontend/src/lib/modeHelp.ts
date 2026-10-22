import type { Mode } from '../api/types'

// Practice offers Echo and Flow only (app style spec §4). `Mode` still names chorus and guided for old attempts,
// which keep their labels (modeName) in Stats, Review and the run lists.
export const MODES: Mode[] = ['echo', 'flow']
export const modeName = (m: Mode): string => m[0].toUpperCase() + m.slice(1)

// Hover text on each mode tab and the help overlay (addendum §6.1).
export function modeHelp(m: Mode): string {
  switch (m) {
    case 'echo': return 'One sentence at a time: listen, then repeat it on your own. You hear the original and your take back to back.'
    case 'flow': return 'Shadow a whole passage without stopping. After: each sentence plays, then you repeat it in the pause. Along: speak at the same time as the audio (use headphones).'
    case 'chorus': case 'guided': return '' // removed modes: never offered, so never explained
    case 'drill': return 'Targeted practice on your weakest tones: listen, record, retry until the target syllables are green.'
  }
}

export const KEY_HELP: [string, string][] = [
  ['Space', 'Play the sentence'], ['Enter', 'Start or stop: record (Echo), Flow'],
  ['← →', 'Previous / next sentence'], ['R', 'Replay your take'], ['S', '0.75× speed'],
  ['T  P  E', 'Hanzi, pinyin, translation'], ['F', 'Flag the sentence'], ['A', 'Send to Anki'], ['L', 'Lesson list'], ['?', 'This help'],
]
