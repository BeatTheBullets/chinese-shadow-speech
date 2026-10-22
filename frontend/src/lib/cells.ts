import type { AlignSpan, Word } from '../api/types'
export type CellStatus = 'ok' | 'close' | 'wrong' | 'suspect' | 'missing' | 'unvoiced' | 'neutral'
export interface Cell { ch: string; pinyin: string; tone: number; score?: number | null; status?: CellStatus; target?: number | null; heard?: number | null; heardSound?: string | null }

/**
 * One cell per alignment span (backend guarantees one span and one syllable per
 * non-punctuation character, in order), so cell i === ref_alignment_json[i].
 * Pinyin/tone come from the i-th flattened syllable. Without alignment, cells come
 * from the syllables themselves (no timing).
 */
export function cellsFromWords(words: Word[] | null | undefined, alignment: AlignSpan[] | null | undefined): Cell[] {
  const syllables = (words ?? []).flatMap((w) => w.syllables)
  if (alignment?.length) {
    return alignment.map((s, i) => {
      const syl = syllables[i]
      return { ch: s.ch, pinyin: syl?.pinyin ?? '', tone: syl?.tone ?? -1, status: 'neutral' as const }
    })
  }
  return syllables.map((s) => ({ ch: s.ch, pinyin: s.pinyin, tone: s.tone, status: 'neutral' as const }))
}
// Phase 2 spec §3: green ok, orange close, red a different tone heard, grey unvoiced, dashed outline missing.
export function cellClass(c: Cell): string {
  return { ok: 'cell-ok', close: 'cell-warn', wrong: 'cell-bad', suspect: 'cell-warn', missing: 'cell-missing', unvoiced: 'cell-unvoiced', neutral: 'cell-neutral' }[c.status ?? 'neutral']
}
