import { describe, expect, it } from 'vitest'
import type { Score } from '../api/types'
import { advance, listened, scored, skip, startDrill, targetsGreen } from './drill'

const sc = (statuses: string[]): Score => ({ overall: 0.5, tone_overall: 0.5, segmental_overall: null, rate_ratio: 1, ref_contour: null, usr_contour: null, warnings: [],
  syllables: statuses.map((s) => ({ ch: 'x', pinyin: 'x', tone: 3, target_tone: 3, heard_tone: 3, status: s as never, tone_score: 0.5, p_target: 0.5, contour: 0.5 })) })

describe('drill steps', () => {
  it('listen → record → review → next when the targets are green', () => {
    let s = listened(startDrill(2))
    expect(s.step).toBe('record')
    s = scored(s, { gated: false, allGreen: true }, 3)
    expect(s).toMatchObject({ step: 'review', tries: 1, outcome: 'next' })
    s = advance(s)
    expect(s).toMatchObject({ i: 1, step: 'listen', tries: 0, outcome: null })
  })
  it('retries until the cap, then moves on', () => {
    let s = listened(startDrill(1))
    s = scored(s, { gated: false, allGreen: false }, 3); expect(s.outcome).toBe('retry')
    s = advance(s); expect(s.step).toBe('record')
    s = scored(s, { gated: false, allGreen: false }, 3); s = advance(s)
    s = scored(s, { gated: false, allGreen: false }, 3)
    expect(s).toMatchObject({ tries: 3, outcome: 'next' })
    expect(advance(s).step).toBe('done')
  })
  it('a gate warning does not count as a try', () => {
    const s = scored(listened(startDrill(1)), { gated: true, allGreen: false }, 3)
    expect(s).toMatchObject({ tries: 0, outcome: 'retry', step: 'review' })
  })
  it('skip goes to the next sentence from any step, and ends after the last', () => {
    expect(skip(startDrill(2))).toMatchObject({ i: 1, step: 'listen' })
    expect(skip({ ...startDrill(1), step: 'record' }).step).toBe('done')
  })
  it('targets are green only when every target syllable is ok', () => {
    expect(targetsGreen(sc(['ok', 'close', 'ok']), [0, 2])).toBe(true)
    expect(targetsGreen(sc(['ok', 'close', 'ok']), [0, 1])).toBe(false)
    expect(targetsGreen({ ...sc(['ok']), overall: null, warnings: ['too_quiet'] }, [0])).toBe(false)
    expect(targetsGreen(null, [0])).toBe(false)
  })
  it('sound kind needs every target sound ok', () => {
    const snd = (status: 'ok' | 'slip') => ({ status, heard: null, heard_pinyin: null, z: 0, rule: 'fused' as const })
    const withSounds = (tone: string, sounds: ({ status: 'ok' | 'slip' } | null)[]): Score => {
      const base = sc(sounds.map(() => tone))
      return { ...base, syllables: base.syllables.map((y, k) => ({ ...y, sound: sounds[k] ? snd(sounds[k]!.status) : null })) }
    }
    expect(targetsGreen(withSounds('ok', [snd('ok'), null]), [0, 1], 'sound')).toBe(false)
    expect(targetsGreen(withSounds('wrong', [snd('ok'), snd('ok')]), [0, 1], 'sound')).toBe(true)
    expect(targetsGreen(withSounds('ok', [snd('ok'), snd('slip')]), [0, 1], 'sound')).toBe(false)
    expect(targetsGreen({ ...withSounds('ok', [snd('ok')]), overall: null }, [0], 'sound')).toBe(false)
  })
})
