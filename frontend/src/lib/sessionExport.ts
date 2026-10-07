import type { Segment } from '../api/types'
import { speechChars } from './text'

const INTERJECTIONS = /^(?:嗯|啊|哦|呃|对|好的|是的|好|是)+$/

// Not worth a listening card (addendum §5.2): fewer than 4 speech characters, or nothing but interjections
// (嗯 啊 哦 呃 对 好 是, and so 嗯嗯 对对 好的 是的).
export function isFiller(text: string): boolean {
  const s = speechChars(text)
  return s.length < 4 || INTERJECTIONS.test(s.join(''))
}

// This session's practised sentences that have no Anki note, in lesson order.
export function sessionUnsent(segments: Segment[], practised: readonly number[]): Segment[] {
  const ids = new Set(practised)
  return segments.filter((s) => ids.has(s.id) && s.anki_note_id == null)
}

// Ticked at first: everything but fillers.
export function initialSelection(segments: Segment[]): Set<number> {
  return new Set(segments.filter((s) => !isFiller(s.text)).map((s) => s.id))
}
