import { describe, expect, it } from 'vitest'
import type { Segment } from '../api/types'
import { initialSelection, isFiller, sessionUnsent } from './sessionExport'

const seg = (id: number, text: string, anki_note_id: number | null = null): Segment => ({
  id, lesson_id: 1, idx: id, start_s: 0, end_s: 1, text, translation: null, words_json: null, ref_alignment_json: null,
  difficulty_flag: false, anki_note_id, last_score: null, best_score: null, attempts: 1,
})

describe('session export', () => {
  it.each([
    ['好的。', true], ['嗯嗯，对对。', true], ['是的是的，好的。', true], ['啊？', true], ['嗯嗯嗯嗯嗯', true], ['ABC', true],
    ['我今天想学中文。', false], ['对，我觉得是', false], ['我们走吧', false],
  ])('isFiller(%s) = %s', (text, want) => { expect(isFiller(text)).toBe(want) })

  it("lists this session's practised sentences not in Anki, in lesson order", () => {
    const segs = [seg(1, '我们走吧'), seg(2, '好的'), seg(3, '我今天想学中文', 9), seg(4, '再见再见吧')]
    expect(sessionUnsent(segs, [4, 1, 3]).map((s) => s.id)).toEqual([1, 4])
    expect([...initialSelection(segs)]).toEqual([1, 3, 4])
  })
})
