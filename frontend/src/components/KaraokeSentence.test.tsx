import { act, cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import KaraokeSentence from './KaraokeSentence'

const words = [{ word: '你好', pinyin: 'nǐhǎo', tones: [3, 3], char_from: 0, char_to: 1, syllables: [] }]
const original = Range.prototype.getClientRects
// jsdom does no layout: give each character a `w` px box at `w` px × its offset in its text node
const boxesOf = (w: number) => function (this: Range) {
  return [{ left: this.startOffset * w, top: 0, width: w, height: w }] as unknown as DOMRectList
}

describe('<KaraokeSentence>', () => {
  afterEach(() => { cleanup(); Range.prototype.getClientRects = original })

  it('keeps the sentence DOM Yomitan reads and draws the wipe on a separate inert layer', () => {
    Range.prototype.getClientRects = boxesOf(40)
    const { container } = render(<KaraokeSentence text="你好。" words={words} showHanzi showPinyin wipe={{ tone: 'ref', progress: 1.5 }} />)
    const p = container.querySelector('p.sentence')!
    expect(p.getAttribute('lang')).toBe('zh')
    expect(p.querySelectorAll('ruby').length).toBe(1)
    expect(p.querySelectorAll('span, div').length).toBe(0)          // no per-character elements in the sentence
    const layer = container.querySelector('[data-testid="wipe"]') as HTMLElement
    expect(layer.getAttribute('aria-hidden')).toBe('true')
    expect(layer.className).toContain('pointer-events-none')
    expect(p.contains(layer)).toBe(false)
    const boxes = [...layer.children] as HTMLElement[]
    expect(boxes.map((b) => [b.style.left, b.style.width])).toEqual([['0px', '40px'], ['40px', '20px']]) // 你 full, 好 half
    expect(boxes[0].style.background).toBe('rgb(143, 179, 217)') // WIPE_FILL.ref (#8fb3d9), not the ref token: visible at night
  })

  it('draws nothing without a wipe, or when the browser gives no character boxes', () => {
    const { container, rerender } = render(<KaraokeSentence text="你好" words={words} showHanzi showPinyin wipe={null} />)
    expect(container.querySelector('[data-testid="wipe"]')).toBeNull()
    rerender(<KaraokeSentence text="你好" words={words} showHanzi showPinyin wipe={{ tone: 'ghost', progress: 2 }} />)
    expect(container.querySelector('[data-testid="wipe"]')!.children.length).toBe(0)
  })

  it('measures again once the web font has loaded and when the window resizes', async () => {
    let w = 40
    Range.prototype.getClientRects = function (this: Range) { return boxesOf(w).call(this) }
    let loaded!: () => void
    const ready = new Promise<void>((r) => { loaded = r })
    Object.defineProperty(document, 'fonts', { configurable: true, value: { ready } })
    try {
      const { container } = render(<KaraokeSentence text="你好" words={words} showHanzi showPinyin wipe={{ tone: 'ref', progress: 2 }} />)
      const widths = () => [...container.querySelector('[data-testid="wipe"]')!.children].map((b) => (b as HTMLElement).style.width)
      expect(widths()).toEqual(['40px', '40px'])
      w = 50
      await act(async () => { loaded(); await ready })
      expect(widths()).toEqual(['50px', '50px'])
      w = 30
      act(() => { window.dispatchEvent(new Event('resize')) })
      expect(widths()).toEqual(['30px', '30px'])
    } finally {
      Reflect.deleteProperty(document, 'fonts')
    }
  })

  it('a sentence wrapped over two lines gets a wipe segment on each line', () => {
    // 你好 on the first line, 再见 wrapped onto the second
    Range.prototype.getClientRects = function (this: Range) {
      const i = this.startOffset
      return [{ left: (i % 2) * 40, top: i < 2 ? 0 : 50, width: 40, height: 40 }] as unknown as DOMRectList
    }
    const { container } = render(<KaraokeSentence text="你好再见" words={null} showHanzi showPinyin wipe={{ tone: 'ref', progress: 3.5 }} />)
    const boxes = [...container.querySelector('[data-testid="wipe"]')!.children] as HTMLElement[]
    expect(boxes.map((b) => [b.style.top, b.style.left, b.style.width])).toEqual([
      ['0px', '0px', '40px'], ['0px', '40px', '40px'], ['50px', '0px', '40px'], ['50px', '40px', '20px'],
    ])
  })

  it('on the sentence card the sentence is large, with its pinyin scaled along; elsewhere (Flow) it is not', () => {
    const { container, rerender } = render(<KaraokeSentence text="你好" words={words} showHanzi showPinyin wipe={null} tools={<span />} />)
    expect(container.querySelector('p.sentence')).toHaveClass('sentence-lg', 'text-[60px]')
    rerender(<KaraokeSentence text="你好" words={words} showHanzi showPinyin wipe={null} />)
    expect(container.querySelector('p.sentence')).not.toHaveClass('sentence-lg')
    expect(container.querySelector('p.sentence')).toHaveClass('text-[40px]')
  })

  it('clicking a character plays that syllable (punctuation skipped); not while selecting text', () => {
    Range.prototype.getClientRects = boxesOf(40)                       // 你 0-40, ，40-80, 好 80-120 (one text node)
    const calls: number[] = []
    const { container } = render(<KaraokeSentence text="你，好" words={null} showHanzi showPinyin wipe={null} tools={<span />} onSyllableClick={(i) => calls.push(i)} />)
    const p = container.querySelector('p.sentence')!
    fireEvent.click(p, { clientX: 100, clientY: 10 })                 // 好: the second syllable
    fireEvent.click(p, { clientX: 10, clientY: 10 })                  // 你
    fireEvent.click(p, { clientX: 60, clientY: 10 })                  // the comma: nothing
    fireEvent.click(p, { clientX: 500, clientY: 10 })                 // past the text: nothing
    expect(calls).toEqual([1, 0])
    const sel = vi.spyOn(window, 'getSelection').mockReturnValue({ isCollapsed: false } as Selection)
    fireEvent.click(p, { clientX: 10, clientY: 10 })
    expect(calls).toEqual([1, 0])
    sel.mockRestore()
  })

  it('the pointer cursor and title show over a character only, not over punctuation or empty space', () => {
    Range.prototype.getClientRects = boxesOf(40)                       // 你 0-40, ，40-80, 好 80-120
    const { container } = render(<KaraokeSentence text="你，好" words={null} showHanzi showPinyin wipe={null} tools={<span />} onSyllableClick={() => {}} />)
    const p = container.querySelector('p.sentence')!, box = p.parentElement!.parentElement! // Sentence's wrapper sits in the box
    const at = (x: number) => { fireEvent.mouseMove(p, { clientX: x, clientY: 10 }); return [box.classList.contains('cursor-pointer'), box.getAttribute('title')] }
    expect(at(500)).toEqual([false, null])
    expect(at(100)).toEqual([true, 'Click a character to hear it'])
    expect(at(60)).toEqual([false, null])
    at(10); fireEvent.mouseLeave(box)
    expect(box).not.toHaveClass('cursor-pointer')
  })

  it('no click target without a handler', () => {
    Range.prototype.getClientRects = boxesOf(40)
    const { container } = render(<KaraokeSentence text="你好" words={null} showHanzi showPinyin wipe={null} tools={<span />} />)
    fireEvent.mouseMove(container.querySelector('p.sentence')!, { clientX: 10, clientY: 10 })
    expect(container.querySelector('.cursor-pointer')).toBeNull()
    expect(container.querySelector('[title]')).toBeNull()
  })
})
