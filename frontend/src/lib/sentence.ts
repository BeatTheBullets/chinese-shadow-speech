import type { Word } from '../api/types'

export interface Run { text: string; pinyin?: string }

export function sentenceRuns(text: string, words: Word[] | null | undefined): Run[] {
  if (!words?.length) return [{ text }]
  const runs: Run[] = []
  let pos = 0
  const flushGap = (to: number) => { if (to > pos) runs.push({ text: text.slice(pos, to) }) }
  for (const w of [...words].sort((a, b) => a.char_from - b.char_from)) {
    if (w.char_from < pos) continue
    flushGap(w.char_from)
    runs.push({ text: text.slice(w.char_from, w.char_to + 1), pinyin: w.pinyin })
    pos = w.char_to + 1
  }
  flushGap(text.length)
  return runs
}

// Steps down with length. `large`: the sentence card's size (Echo, Drill), 1.5× each step, the one big text on screen.
// Literal classes, so Tailwind sees them.
export function fontSizeClass(len: number, large = false): string {
  if (len <= 10) return large ? 'text-[60px]' : 'text-[40px]'
  if (len <= 18) return large ? 'text-[48px]' : 'text-[32px]'
  if (len <= 25) return large ? 'text-[42px]' : 'text-[28px]'
  return large ? 'text-[36px]' : 'text-[24px]'
}
