import { describe, it, expect } from 'vitest'
import { sentenceRuns, fontSizeClass } from './sentence'

const words = [
  { word: '我', pinyin: 'wǒ', tones: [3], char_from: 0, char_to: 0, syllables: [] },
  { word: '今天', pinyin: 'jīntiān', tones: [1, 1], char_from: 1, char_to: 2, syllables: [] },
]
describe('sentenceRuns', () => {
  it('covers text with word runs and bare punctuation', () => {
    expect(sentenceRuns('我今天。', words)).toEqual([{ text: '我', pinyin: 'wǒ' }, { text: '今天', pinyin: 'jīntiān' }, { text: '。' }])
  })
  it('falls back to one bare run without words', () => {
    expect(sentenceRuns('你好。', null)).toEqual([{ text: '你好。' }])
  })
  it('falls back to one bare run for an empty word list', () => {
    expect(sentenceRuns('你好。', [])).toEqual([{ text: '你好。' }])
  })
  it('fills gaps when words do not cover text', () => {
    expect(sentenceRuns('我今天呢', words)).toEqual([{ text: '我', pinyin: 'wǒ' }, { text: '今天', pinyin: 'jīntiān' }, { text: '呢' }])
  })
})
describe('fontSizeClass', () => {
  it('steps down with length', () => {
    expect(fontSizeClass(8)).toBe('text-[40px]'); expect(fontSizeClass(18)).toBe('text-[32px]')
    expect(fontSizeClass(25)).toBe('text-[28px]'); expect(fontSizeClass(40)).toBe('text-[24px]')
  })
})
