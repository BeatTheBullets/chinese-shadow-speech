import { describe, it, expect } from 'vitest'
import { groupBySpeaker } from './library'
import type { Lesson } from '../api/types'

const L = (id: number, speaker: string, created: string): Lesson => ({ id, title: `t${id}`, speaker, source_type: 'upload', source_ref: '', duration_s: 0, created_at: created, status: 'ready', error: null, segment_count: 1, practised_count: 0, mean_last_score: null })

describe('groupBySpeaker', () => {
  it('pins the language parent and orders groups by recency', () => {
    const g = groupBySpeaker([L(1, 'A', '2026-01-01'), L(2, 'B', '2026-03-01'), L(3, 'A', '2026-02-01')], 'B')
    expect(g.map((x) => x.speaker)).toEqual(['B', 'A'])
    expect(g[0].pinned).toBe(true)
    expect(g[1].lessons.map((l) => l.id)).toEqual([3, 1])
  })
  it('groups empty speaker as Unsorted', () => {
    expect(groupBySpeaker([L(1, '', '2026-01-01')], null)[0].speaker).toBe('Unsorted')
  })
})
