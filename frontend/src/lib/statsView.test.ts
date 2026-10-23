import { describe, expect, it } from 'vitest'
import { changeText, scoreText } from './statsView'

const s = (last7: number | null, prev7: number | null) => ({ value: 0.5, last7, prev7, n: 40 })

describe('statsView', () => {
  it('scoreText shows a dash only for null; 0 is "0"', () => {
    expect(scoreText(null)).toBe('—')
    expect(scoreText(0)).toBe('0')
    expect(scoreText(0.734)).toBe('73')
  })
  it('changeText needs both weeks', () => {
    expect(changeText(s(0.8, null))).toBe('—')
    expect(changeText(s(null, 0.8))).toBe('—')
    expect(changeText(s(0.8, 0.75))).toBe('▲ 5')
    expect(changeText(s(0.7, 0.73))).toBe('▼ 3')
    expect(changeText(s(0.5, 0.5))).toBe('±0')
  })
})
