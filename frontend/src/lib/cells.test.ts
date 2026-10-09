import { describe, it, expect } from 'vitest'
import { cellsFromWords, cellClass } from './cells'
import type { AlignSpan, Word } from '../api/types'

const syl = (ch: string, tone: number) => ({ ch, pinyin: ch + tone, pinyin_toneless: ch, tone })
const words: Word[] = [{ word: '你好', pinyin: 'nǐhǎo', tones: [2, 3], char_from: 0, char_to: 1, syllables: [syl('你', 2), syl('好', 3)] }]
const span = (ch: string, start: number, end: number): AlignSpan => ({ ch, start, end, conf: 1 })

describe('cells', () => {
  it('one cell per alignment span, pinyin/tone by position', () => {
    const c = cellsFromWords(words, [span('你', 1, 1.2), span('好', 1.2, 1.5)])
    expect(c.map((x) => [x.ch, x.tone, x.pinyin])).toEqual([['你', 2, '你2'], ['好', 3, '好3']])
    expect(c[0].status).toBe('neutral')
  })
  it('falls back to flattened syllables without alignment', () => {
    expect(cellsFromWords(words, null).map((x) => [x.ch, x.tone])).toEqual([['你', 2], ['好', 3]])
    expect(cellsFromWords(words, []).map((x) => x.ch)).toEqual(['你', '好'])
  })
  it('empty when nothing is available', () => {
    expect(cellsFromWords(null, null)).toEqual([])
  })
  it('keeps position alignment with digits/Latin and 「」 punctuation', () => {
    const w: Word[] = [
      { word: '「', pinyin: '', tones: [], char_from: 0, char_to: 0, syllables: [] },
      { word: '我', pinyin: 'wǒ', tones: [3], char_from: 1, char_to: 1, syllables: [syl('我', 3)] },
      { word: '3', pinyin: 'sān', tones: [1], char_from: 2, char_to: 2, syllables: [syl('3', 1)] },
      { word: 'A', pinyin: 'A', tones: [-1], char_from: 3, char_to: 3, syllables: [syl('A', -1)] },
      { word: '」', pinyin: '', tones: [], char_from: 4, char_to: 4, syllables: [] },
    ]
    const spans = [span('我', 0, 1), span('3', 1, 2), span('A', 2, 3)]
    const c = cellsFromWords(w, spans)
    expect(c.map((x) => [x.ch, x.tone])).toEqual([['我', 3], ['3', 1], ['A', -1]])
  })
  it('renders cells without pinyin when syllables are missing or short', () => {
    const c = cellsFromWords(words, [span('你', 0, 1), span('好', 1, 2), span('吗', 2, 3)])
    expect(c.map((x) => x.ch)).toEqual(['你', '好', '吗'])
    expect(c[2]).toMatchObject({ pinyin: '', tone: -1 })
    expect(cellsFromWords(null, [span('你', 0, 1)])[0]).toMatchObject({ ch: '你', pinyin: '', tone: -1 })
  })
  it('classes by status and score thresholds', () => {
    expect(cellClass({ ch: 'x', pinyin: '', tone: 1, status: 'ok' })).toBe('cell-ok')
    expect(cellClass({ ch: 'x', pinyin: '', tone: 1, status: 'close' })).toBe('cell-warn')
    expect(cellClass({ ch: 'x', pinyin: '', tone: 1, status: 'wrong' })).toBe('cell-bad')
    expect(cellClass({ ch: 'x', pinyin: '', tone: 1, status: 'missing' })).toBe('cell-missing')
  })
})
