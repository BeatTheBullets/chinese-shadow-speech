import { render } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import Sentence from './Sentence'

const words = [{ word: '今天', pinyin: 'jīntiān', tones: [1, 1], char_from: 0, char_to: 1, syllables: [] }]

describe('<Sentence>', () => {
  it('renders one ruby per word with rt pinyin and contiguous text', () => {
    const { container } = render(<Sentence text="今天。" words={words} showPinyin showHanzi />)
    const p = container.querySelector('p.sentence')!
    expect(p.getAttribute('lang')).toBe('zh')
    expect(p.querySelectorAll('ruby').length).toBe(1)
    expect(p.querySelector('rt')!.textContent).toBe('jīntiān')
    expect(p.querySelectorAll('span').length).toBe(0)
    const visible = [...p.childNodes].map((n) => (n.nodeName === 'RUBY' ? n.firstChild!.textContent : n.textContent)).join('')
    expect(visible).toBe('今天。')
  })
  it('hides pinyin via class only', () => {
    const { container } = render(<Sentence text="今天" words={words} showPinyin={false} showHanzi />)
    expect(container.querySelector('p.sentence')!.classList.contains('hide-pinyin')).toBe(true)
    expect(container.querySelector('rt')).not.toBeNull()
  })
  it('survives missing words', () => {
    const { container } = render(<Sentence text="你好。" words={null} showPinyin showHanzi />)
    const p = container.querySelector('p.sentence')!
    expect(p.textContent).toBe('你好。')
    expect(p.querySelector('ruby')).toBeNull()
  })
  it('renders a placeholder without the text when hanzi is hidden', () => {
    const { container } = render(<Sentence text="今天。" words={words} showPinyin showHanzi={false} translation="Today." showTranslation />)
    const p = container.querySelector('p.sentence')!
    expect(p.classList.contains('placeholder')).toBe(true)
    expect(container.textContent).not.toContain('今天')
    expect(container.textContent).toContain('Today.')
  })
})
