import { describe, expect, it } from 'vitest'
import type { Passage, Segment } from '../api/types'
import { groupByPassage, passageDone, passageIndexOf, passageSpan } from './passages'

const seg = (id: number, attempts = 0): Segment => ({
  id, lesson_id: 1, idx: id, start_s: id, end_s: id + 1, text: 't', translation: null, words_json: null, ref_alignment_json: null,
  difficulty_flag: false, anki_note_id: null, last_score: null, best_score: null, attempts,
})
const p = (idx: number, ids: number[]): Passage => ({ idx, title: `P${idx + 1}`, start_s: 0, end_s: 1, segment_ids: ids, done: false })
const segments = [seg(10, 1), seg(11), seg(12), seg(13)]
const passages = [p(0, [10, 11]), p(1, [12, 13])]

describe('passages', () => {
  it('finds the passage of a sentence and its sentence range', () => {
    expect([0, 1, 2, 3, 9].map((i) => passageIndexOf(passages, segments, i))).toEqual([0, 0, 1, 1, -1])
    expect(passageSpan(passages[1], segments)).toEqual({ from: 2, to: 3 })
    expect(passageSpan(p(2, [99]), segments)).toBeNull()
  })
  it('is done when every sentence has an attempt, on the server or in this session', () => {
    expect(passageDone(passages[0], segments, [])).toBe(false)
    expect(passageDone(passages[0], segments, [11])).toBe(true)
    expect(passageDone(p(2, []), segments, [])).toBe(false)
  })
  it('groups the drawer by passage; sentences no passage lists come last', () => {
    const g = groupByPassage([...segments, seg(14)], passages)
    expect(g.map((x) => [x.passage?.title ?? null, x.rows.map((r) => r.i)])).toEqual([['P1', [0, 1]], ['P2', [2, 3]], [null, [4]]])
    expect(groupByPassage(segments, []).map((x) => x.passage)).toEqual([null])
  })
})
