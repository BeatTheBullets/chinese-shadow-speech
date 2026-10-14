import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import CellRow from './CellRow'

describe('<CellRow>', () => {
  it('shows score, target→heard on a wrong tone, ∅ unvoiced and – missing', () => {
    render(<CellRow variant="you" cells={[
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
})
