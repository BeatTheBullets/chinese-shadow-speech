import { describe, it, expect } from 'vitest'
import { flaggedFirst, activityBars } from './stats'
import type { LessonDetail } from '../api/types'
const L = (id: number, created: string, segs: Partial<LessonDetail['segments'][number]>[]): LessonDetail => ({
  id, title: 't', speaker: '', source_type: 'upload', source_ref: '', duration_s: 0, created_at: created, status: 'ready', error: null, segment_count: segs.length, practised_count: 0, mean_last_score: null,
  segments: segs.map((s, i) => ({ id: id * 10 + i, lesson_id: id, idx: i, start_s: 0, end_s: 1, text: 'x', translation: null, words_json: null, ref_alignment_json: null, difficulty_flag: false, anki_note_id: null, last_score: null, best_score: null, attempts: 0, ...s })),
})
describe('stats helpers', () => {
  it('flaggedFirst picks flagged or weak, oldest lesson first', () => {
    const rows = flaggedFirst([L(2, '2026-02-01', [{ difficulty_flag: true }]), L(1, '2026-01-01', [{ last_score: 0.5 }, { last_score: 0.9 }])])
    expect(rows.map((r) => r.segment.id)).toEqual([10, 20])
  })
  it('activityBars labels weekdays', () => {
    expect(activityBars([{ date: '2026-10-05', minutes: 3, attempts: 2 }])[0]).toEqual({ label: 'M', minutes: 3, attempts: 2 })
  })
  it('activityBars rounds minutes to one decimal for display', () => {
    expect(activityBars([{ date: '2026-10-05', minutes: 3.3333333333333335, attempts: 1 }])[0].minutes).toBe(3.3)
  })
  it('activityBars labels by the UTC weekday (Sunday and Saturday)', () => {
    expect(activityBars([{ date: '2026-10-04', minutes: 0, attempts: 0 }, { date: '2026-10-10', minutes: 0, attempts: 0 }]).map((b) => b.label)).toEqual(['S', 'S'])
    expect(activityBars([{ date: '2026-10-06', minutes: 0, attempts: 0 }, { date: '2026-10-07', minutes: 0, attempts: 0 }]).map((b) => b.label)).toEqual(['T', 'W'])
  })
})
