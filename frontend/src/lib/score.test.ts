import { describe, expect, it } from 'vitest'
import type { Score, ScoredSyllable, Segment } from '../api/types'
import type { Cell } from './cells'
import { applyAttempt, cellTitle, isWarningText, noticeText, pct, warningText, withScore } from './score'

const cells: Cell[] = [{ ch: '你', pinyin: 'ní', tone: 3, status: 'neutral' }, { ch: '好', pinyin: 'hǎo', tone: 3, status: 'neutral' }]
const syl = (o: Partial<ScoredSyllable>): ScoredSyllable => ({ ch: '你', pinyin: 'ní', tone: 3, target_tone: 2, heard_tone: 2, status: 'ok', tone_score: 0.9, p_target: 0.9, contour: 0.9, ...o })
const score = (o: Partial<Score> = {}): Score => ({ overall: 0.7, tone_overall: 0.7, segmental_overall: null, rate_ratio: 1, ref_contour: null, usr_contour: null,
  syllables: [syl({}), syl({ ch: '好', target_tone: 3, heard_tone: 2, status: 'wrong', tone_score: 0.3 })], warnings: [], ...o })

describe('score', () => {
  it('puts each syllable verdict on its cell', () => {
    const out = withScore(cells, score())
    expect(out.map((c) => c.status)).toEqual(['ok', 'wrong'])
    expect(out[1]).toMatchObject({ score: 0.3, target: 3, heard: 2 })
  })
  it('leaves cells alone without a score or when the counts differ', () => {
    expect(withScore(cells, null)).toBe(cells)
    expect(withScore(cells, score({ syllables: [syl({})] }))).toBe(cells)
  })
  it('explains a gated take', () => {
    expect(warningText(score({ overall: null, warnings: ['too_quiet'] }))).toBe('Too quiet — not scored. Move closer to the mic.')
    expect(warningText(score({ overall: null, warnings: ['odd_code'] }))).toBe('Not scored (odd_code).')
    expect(warningText(score({ overall: null, warnings: ['ref_align_failed'] })))
      .toBe("This sentence's reference timing is broken — not scored. Rebuild the lesson text.")
    expect(warningText(score())).toBeNull()
  })
  it('says what it heard when the words were different', () => {
    expect(warningText(score({ overall: null, warnings: ['different_words'], heard_text: '我是学生' })))
      .toBe('Heard different words — not scored. Heard: 我是学生')
    expect(warningText(score({ overall: null, warnings: ['different_words'], heard_text: null }))).toBe('Heard different words — not scored.')
    expect(isWarningText('Heard different words — not scored. Heard: 我是学生')).toBe(true)
  })
  it('a scored take whose words partly differed says what was heard', () => {
    const differ = score({ notices: ['words_differ'], heard_text: '他们在次微笑' })
    expect(noticeText(differ)).toBe('Some words sounded different — heard: 他们在次微笑')
    expect(warningText(differ)).toBeNull()                                                // scored: the header shows the score
    expect(noticeText(score({ notices: [], heard_text: '你好' }))).toBeNull()
    expect(noticeText(score({ heard_text: '你好' }))).toBeNull()                         // old score JSON: no notices
    expect(noticeText(score({ overall: null, warnings: ['too_quiet'], notices: ['words_differ'] }))).toBeNull()
    expect(isWarningText('Some words sounded different — heard: 他们在次微笑')).toBe(true)
    expect(noticeText(score({ notices: ['words_differ'], heard_text: null }))).toBe('Some words sounded different.')
    expect(noticeText(score({ notices: ['words_differ'], heard_text: '' }))).toBe('Some words sounded different.')
    expect(isWarningText('Some words sounded different.')).toBe(true)
  })
  it('recognises its own warning texts, and only those', () => {
    expect(isWarningText('Too quiet — not scored. Move closer to the mic.')).toBe(true)
    expect(isWarningText('Not scored (odd_code).')).toBe(true)
    expect(isWarningText('Several tries on this one. Move on and come back later.')).toBe(false)
    expect(isWarningText('')).toBe(false)
  })
  it('formats percentages and cell titles', () => {
    expect(pct(0.456)).toBe('46'); expect(pct(null)).toBe('—')
    expect(cellTitle({ ...cells[1], status: 'wrong', score: 0.41, target: 3, heard: 2 })).toBe('hǎo · Speaker: tone 3 (low) · You: tone 2 (rising) · 41')
    expect(cellTitle(cells[0])).toBe('ní')
  })
})

describe('applyAttempt', () => {
  const s = { id: 1, last_score: 0.5, best_score: 0.6, attempts: 2 } as Segment
  it('counts the attempt and moves last and best', () => {
    expect(applyAttempt(s, 0.8)).toMatchObject({ attempts: 3, last_score: 0.8, best_score: 0.8 })
    expect(applyAttempt(s, 0.4)).toMatchObject({ attempts: 3, last_score: 0.4, best_score: 0.6 })
  })
  it('an unscored take only counts', () => {
    expect(applyAttempt(s, null)).toMatchObject({ attempts: 3, last_score: 0.5, best_score: 0.6 })
  })
})
