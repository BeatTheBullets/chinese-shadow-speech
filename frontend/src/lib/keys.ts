export type Action = 'play' | 'record' | 'chorus' | 'prev' | 'next' | 'flag' | 'toggleHanzi' | 'togglePinyin' | 'toggleTranslation' | 'toggleDrawer' | 'exportAnki' | 'replayYou' | 'speed075' | 'help'
export const KEYMAP: Record<string, Action> = {
  ' ': 'play', Enter: 'record', c: 'chorus', ArrowLeft: 'prev', ArrowRight: 'next', f: 'flag',
  t: 'toggleHanzi', p: 'togglePinyin', e: 'toggleTranslation', l: 'toggleDrawer', a: 'exportAnki', r: 'replayYou', s: 'speed075', '?': 'help',
}
// False while the user is typing (form fields, anything inside a contenteditable region) and for anything inside
// a dialog, whose own buttons keep Space/Enter.
export function shouldHandleKey(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el || !el.tagName) return true
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)) return false
  return !(el.isContentEditable || !!el.closest?.('[contenteditable="true"], [role="dialog"]'))
}
type KeyLike = Pick<KeyboardEvent, 'key' | 'target' | 'ctrlKey' | 'metaKey' | 'altKey' | 'repeat'>
// The app action for a keydown, or null when the key belongs to the browser (Ctrl/Cmd/Alt chords such as
// Ctrl+C or Ctrl+R), is an auto-repeat, or was typed into a text field.
export function actionForKey(e: KeyLike): Action | null {
  if (e.ctrlKey || e.metaKey || e.altKey || e.repeat || !shouldHandleKey(e.target)) return null
  return Object.prototype.hasOwnProperty.call(KEYMAP, e.key) ? KEYMAP[e.key] : null
}
