import { describe, it, expect } from 'vitest'
import { deleteConfirmText, groupBySpeaker, needsPolling, renamePatch } from './library'
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

describe('needsPolling', () => {
  it('is true only while a lesson is queued or processing', () => {
    expect(needsPolling([L(1, 'A', '2026-01-01')])).toBe(false)
    expect(needsPolling([L(1, 'A', '2026-01-01'), { ...L(2, 'A', '2026-01-02'), status: 'processing' }])).toBe(true)
    expect(needsPolling([{ ...L(1, 'A', '2026-01-01'), status: 'queued' }])).toBe(true)
    expect(needsPolling([{ ...L(1, 'A', '2026-01-01'), status: 'error' }])).toBe(false)
    expect(needsPolling([])).toBe(false)
  })
})

describe('deleteConfirmText', () => {
  it('names the lesson and what goes with it', () => {
    const t = deleteConfirmText({ ...L(1, 'A', '2026-01-01'), title: '春天的茶', segment_count: 12, practised_count: 3 })
    expect(t).toMatch(/春天的茶/); expect(t).toMatch(/12 sentences/); expect(t).toMatch(/practice history/); expect(t).toMatch(/cannot be undone/)
  })
  it('says so when the lesson is still processing', () => {
    expect(deleteConfirmText({ ...L(1, 'A', '2026-01-01'), status: 'processing' })).toMatch(/still processing/)
    expect(deleteConfirmText({ ...L(1, 'A', '2026-01-01'), status: 'error' })).not.toMatch(/still processing/)
  })
})

describe('renamePatch', () => {
  const l = { ...L(1, 'Old speaker', '2026-01-01'), title: 'Old title' }
  it('is null when either prompt is cancelled', () => {
    expect(renamePatch(l, null, 'X')).toBeNull()
    expect(renamePatch(l, 'X', null)).toBeNull()
  })
  it('sends only the changed, trimmed fields', () => {
    expect(renamePatch(l, '  New title ', 'Old speaker')).toEqual({ title: 'New title' })
    expect(renamePatch(l, 'Old title', ' New speaker')).toEqual({ speaker: 'New speaker' })
    expect(renamePatch(l, 'T', 'S')).toEqual({ title: 'T', speaker: 'S' })
  })
  it('is null when nothing changed, and keeps the title when it is cleared', () => {
    expect(renamePatch(l, 'Old title', 'Old speaker')).toBeNull()
    expect(renamePatch(l, '   ', 'Old speaker')).toBeNull()
  })
  it('allows clearing the speaker (the lesson moves to Unsorted)', () => {
    expect(renamePatch(l, 'Old title', '')).toEqual({ speaker: '' })
  })
})
