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

// What each key does, in the words of the button it presses (spec §1.3: same action, same word, same key).
// Keys sharing a row are separated by spaces; the help shows each as its own key cap.
export const KEY_HELP: [string, string][] = [
  ['← →', 'Previous / next sentence'], ['Space', 'Listen: play the sentence'],
  ['Enter', 'Record or stop (Echo); start or stop the run (Flow)'], ['R', 'Me: replay your take'],
  ['A', 'Anki: send the sentence to Anki'], ['S', '0.75× speed on or off'], ['F', 'Difficult: flag the sentence'],
  ['T P E', 'Show or hide characters, pinyin, English'], ['L', 'Lesson list'], ['?', 'This help'],
]
