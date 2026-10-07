import { describe, expect, it } from 'vitest'
import { addQuestion, bookmarkletCode } from './handoff'

describe('hand-off', () => {
  it('builds the bookmarklet for the app origin', () => {
    expect(bookmarkletCode('http://127.0.0.1:5173')).toBe("javascript:location.href='http://127.0.0.1:5173/library?add='+encodeURIComponent(location.href)")
  })
  it('asks with the title and the link when there is a title, else the link', () => {
    expect(addQuestion('https://youtu.be/x', null)).toBe('Add https://youtu.be/x to chinese-shadow-speech?')
    expect(addQuestion('https://youtu.be/x', ' 学中文 ')).toBe('Add 学中文 (https://youtu.be/x) to chinese-shadow-speech?')
  })
})
