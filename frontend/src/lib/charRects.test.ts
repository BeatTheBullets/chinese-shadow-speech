import { afterEach, describe, expect, it } from 'vitest'
import { charRects } from './charRects'

const original = Range.prototype.getClientRects

describe('charRects', () => {
  afterEach(() => { Range.prototype.getClientRects = original; document.body.innerHTML = '' })

  it('one box per visible character, relative to the container, skipping the pinyin', () => {
    document.body.innerHTML = '<div id="box"><p id="p"><ruby>你好<rt>nǐhǎo</rt></ruby>。</p></div>'
    const box = document.getElementById('box')!, p = document.getElementById('p')!
    box.getBoundingClientRect = () => ({ left: 100, top: 10 }) as DOMRect
    Range.prototype.getClientRects = function (this: Range) {
      const base = this.startContainer.textContent === '。' ? 200 : 100
      return [{ left: base + this.startOffset * 40, top: 30, width: 40, height: 48 }] as unknown as DOMRectList
    }
    expect(charRects(p, box)).toEqual([
      { left: 0, top: 20, width: 40, height: 48 }, { left: 40, top: 20, width: 40, height: 48 }, { left: 100, top: 20, width: 40, height: 48 },
    ])
  })

  it('null where the browser gives no box', () => {
    document.body.innerHTML = '<div id="box"><p id="p">你好</p></div>'
    Range.prototype.getClientRects = () => [] as unknown as DOMRectList
    expect(charRects(document.getElementById('p')!, document.getElementById('box')!)).toEqual([null, null])
  })

  it('takes the widest of the client rectangles of a character, not an empty first one', () => {
    document.body.innerHTML = '<div id="box"><p id="p">你</p></div>'
    const box = document.getElementById('box')!
    box.getBoundingClientRect = () => ({ left: 0, top: 0 }) as DOMRect
    Range.prototype.getClientRects = () => [
      { left: 300, top: 0, width: 0, height: 48 }, { left: 0, top: 60, width: 40, height: 48 },
    ] as unknown as DOMRectList
    expect(charRects(document.getElementById('p')!, box)).toEqual([{ left: 0, top: 60, width: 40, height: 48 }])
  })
})
