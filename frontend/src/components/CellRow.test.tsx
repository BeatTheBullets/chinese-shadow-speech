import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import CellRow from './CellRow'

describe('<CellRow>', () => {
  it('shows score, target→heard on a wrong tone, ∅ unvoiced and – missing', () => {
    render(<CellRow cells={[
      { ch: '你', pinyin: 'ní', tone: 3, status: 'ok', score: 0.92, target: 2, heard: 2 },
      { ch: '好', pinyin: 'hǎo', tone: 3, status: 'wrong', score: 0.31, target: 3, heard: 2 },
      { ch: '吗', pinyin: 'ma', tone: 0, status: 'unvoiced', score: null },
      { ch: '呢', pinyin: 'ne', tone: 0, status: 'missing', score: 0 },
    ]} />)
    const [ok, wrong, unvoiced, missing] = screen.getAllByRole('button')
    expect(ok).toHaveClass('cell-ok'); expect(ok).toHaveTextContent('92')
    expect(wrong).toHaveClass('cell-bad'); expect(wrong).toHaveTextContent('3→2')
    expect(unvoiced).toHaveClass('cell-unvoiced'); expect(unvoiced).toHaveTextContent('∅')
    expect(missing).toHaveClass('cell-missing'); expect(missing).toHaveTextContent('–')
    expect(wrong).toHaveAttribute('title', 'hǎo · Speaker: tone 3 (low) · You: tone 2 (rising) · 31')
  })

  it('every cell has the same fixed size, lines that cannot wrap, and the row aligns them at the top', () => {
    const { container } = render(<CellRow cells={[
      { ch: '王', pinyin: 'wáng', tone: 2, status: 'wrong', score: 0.2, target: 2, heard: 1 }, { ch: '小', pinyin: 'xiǎo', tone: 3, status: 'ok', score: 0.93 },
    ]} />)
    expect(container.firstElementChild).toHaveClass('items-start')
    for (const b of screen.getAllByRole('button')) {
      expect(b).toHaveClass('w-12', 'h-14', 'shrink-0', 'overflow-hidden', 'whitespace-nowrap')
      for (const line of b.querySelectorAll('span')) expect(line).toHaveClass('truncate')
    }
  })

  it('outlines the highlighted cells only, and a click plays that cell', () => {
    const calls: number[] = []
    render(<CellRow highlight={[1]} onCellClick={(i) => calls.push(i)} cells={[
      { ch: '你', pinyin: 'nǐ', tone: 3 }, { ch: '好', pinyin: 'hǎo', tone: 3 }, { ch: '吗', pinyin: 'ma', tone: 0 },
    ]} />)
    const [a, b, c] = screen.getAllByRole('button')
    expect(b).toHaveClass('ring-2', 'ring-accent')
    expect(a).not.toHaveClass('ring-2'); expect(c).not.toHaveClass('ring-2')
    b.click(); expect(calls).toEqual([1])
  })
})
