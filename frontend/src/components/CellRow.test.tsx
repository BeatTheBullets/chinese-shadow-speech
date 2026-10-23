import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Cell } from '../lib/cells'
import CellRow from './CellRow'

const compare = (cell: HTMLElement) => within(cell).getByTestId('cell-compare')

describe('<CellRow>', () => {
  it('shows score, target→heard on a wrong tone, ∅ unvoiced and – missing', () => {
    render(<CellRow cells={[
      { ch: '你', pinyin: 'ní', tone: 3, status: 'ok', score: 0.92, target: 2, heard: 2 },
      { ch: '好', pinyin: 'hǎo', tone: 3, status: 'wrong', score: 0.31, target: 3, heard: 2 },
      { ch: '吗', pinyin: 'ma', tone: 0, status: 'unvoiced', score: null },
      { ch: '呢', pinyin: 'ne', tone: 0, status: 'missing', score: 0 },
    ]} />)
    const [ok, wrong, unvoiced, missing] = screen.getAllByTestId('cell')
    expect(ok).toHaveClass('cell-ok'); expect(compare(ok)).toHaveTextContent('92')
    expect(wrong).toHaveClass('cell-bad'); expect(compare(wrong)).toHaveTextContent('3→2')
    expect(unvoiced).toHaveClass('cell-unvoiced'); expect(compare(unvoiced)).toHaveTextContent('∅')
    expect(missing).toHaveClass('cell-missing'); expect(compare(missing)).toHaveTextContent('–')
    expect(compare(wrong).title).toContain('hǎo · Speaker: tone 3 (low) · You: tone 2 (rising) · 31')
  })

  it('the hover hint says "then you" only when the cell has a take of yours', () => {
    render(<CellRow cells={[
      { ch: '你', pinyin: 'ní', tone: 3, status: 'ok', score: 0.92, target: 2, heard: 2 },
      { ch: '吗', pinyin: 'ma', tone: 0, status: 'unvoiced', score: null },
      { ch: '呢', pinyin: 'ne', tone: 0, status: 'missing', score: 0 },
    ]} />)
    const [ok, unvoiced, missing] = screen.getAllByTestId('cell')
    expect(compare(ok).title).toMatch(/click: the speaker, then you$/)
    expect(compare(unvoiced).title).toMatch(/click: the speaker$/)
    expect(compare(missing).title).toMatch(/click: the speaker$/)
  })

  it('every cell has the same fixed size, tall enough for its buttons, lines that cannot wrap, and the row aligns them at the top', () => {
    const { container } = render(<CellRow cells={[
      { ch: '王', pinyin: 'wáng', tone: 2, status: 'wrong', score: 0.2, target: 2, heard: 1 }, { ch: '小', pinyin: 'xiǎo', tone: 3, status: 'ok', score: 0.93 },
    ]} />)
    expect(container.firstElementChild).toHaveClass('items-start', 'flex-wrap', 'justify-center', 'gap-2')
    for (const c of screen.getAllByTestId('cell')) {
      expect(c).toHaveClass('w-[72px]', 'h-24', 'shrink-0', 'overflow-hidden', 'whitespace-nowrap')
      for (const line of compare(c).querySelectorAll('span')) expect(line).toHaveClass('truncate')
    }
  })

  it('is about twice the old size: 28 px hanzi, tone and score on their own 13/12 px lines, 28 x 24 buttons with 14 px icons', () => {
    render(<CellRow cells={[{ ch: '王', pinyin: 'wáng', tone: 2, status: 'ok', score: 0.9 }]} />)
    const lines = compare(screen.getByTestId('cell')).querySelectorAll('span')
    expect(lines[0]).toHaveClass('text-[28px]'); expect(lines[1]).toHaveClass('text-[13px]'); expect(lines[2]).toHaveClass('text-xs')
    for (const name of ['Speaker says 王', 'You say 王']) {
      const b = screen.getByRole('button', { name })
      expect(b).toHaveClass('w-7', 'h-6', '[&_svg]:w-3.5', '[&_svg]:h-3.5')
    }
  })

  it('a heard sound sits in a slot directly under its own card (so it stays aligned on wrap); every card reserves the slot once any slipped', () => {
    const { container } = render(<CellRow cells={[
      { ch: '吃', pinyin: 'chī', tone: 1, heardSound: 'cī' }, { ch: '苹', pinyin: 'píng', tone: 2 },
    ]} />)
    const slots = container.querySelectorAll('[data-slot]')
    expect(slots).toHaveLength(2)
    expect(Array.from(slots).map((s) => s.textContent)).toEqual(['cī', ''])
    expect(slots[0]).toHaveAttribute('title', 'heard cī instead of chī')
    expect(slots[0]).toHaveClass('w-[72px]', 'border-dashed', 'border-sound')
    expect(slots[0].previousElementSibling).toBe(screen.getAllByTestId('cell')[0])
  })
  it('has no heard slots without slips', () => {
    const { container } = render(<CellRow cells={[{ ch: '吃', pinyin: 'chī', tone: 1 }]} />)
    expect(container.querySelectorAll('[data-slot]')).toHaveLength(0)
  })

  it('outlines the highlighted cells only', () => {
    render(<CellRow highlight={[1]} cells={[
      { ch: '你', pinyin: 'nǐ', tone: 3 }, { ch: '好', pinyin: 'hǎo', tone: 3 }, { ch: '吗', pinyin: 'ma', tone: 0 },
    ]} />)
    const [a, b, c] = screen.getAllByTestId('cell')
    expect(b).toHaveClass('ring-2', 'ring-accent')
    expect(a).not.toHaveClass('ring-2'); expect(c).not.toHaveClass('ring-2')
  })

  const scored: Cell[] = [
    { ch: '王', pinyin: 'wáng', tone: 2, status: 'ok', score: 0.91 }, { ch: '小', pinyin: 'xiǎo', tone: 3, status: 'wrong', score: 0.3, target: 3, heard: 2 },
    { ch: '姐', pinyin: 'jiě', tone: 3, status: 'missing', score: 0 }, { ch: '们', pinyin: 'men', tone: 0, status: 'unvoiced', score: null },
  ]
  it('every cell has a speaker and a me button, labelled with its character, in the speaker and you colours', () => {
    render(<CellRow cells={scored} />)
    for (const c of scored) {
      const sp = screen.getByRole('button', { name: `Speaker says ${c.ch}` }), me = screen.getByRole('button', { name: `You say ${c.ch}` })
      expect(sp).toHaveAttribute('title', `Speaker says ${c.ch}`); expect(me).toHaveAttribute('title', `You say ${c.ch}`)
      expect(sp).toHaveClass('text-ref'); expect(me).toHaveClass('text-you')
    }
  })
  it('speaker plays the reference syllable i, me the user’s, and the character itself the speaker then you', () => {
    const calls: string[] = []
    render(<CellRow cells={scored} onSpeaker={(i) => calls.push(`speaker ${i}`)} onMe={(i) => calls.push(`me ${i}`)} onCellClick={(i) => calls.push(`compare ${i}`)} />)
    fireEvent.click(screen.getByRole('button', { name: 'Speaker says 小' }))
    fireEvent.click(screen.getByRole('button', { name: 'You say 小' }))
    fireEvent.click(compare(screen.getAllByTestId('cell')[0]))
    expect(calls).toEqual(['speaker 1', 'me 1', 'compare 0'])
  })
  it('me does nothing on a missing or unvoiced cell, or before a score (nothing of yours to play); speaker still plays', () => {
    const calls: string[] = []
    render(<CellRow cells={[...scored, { ch: '呢', pinyin: 'ne', tone: 0, status: 'neutral' }]} onSpeaker={(i) => calls.push(`speaker ${i}`)} onMe={(i) => calls.push(`me ${i}`)} />)
    for (const ch of ['姐', '们', '呢']) {
      const me = screen.getByRole('button', { name: `You say ${ch}` })
      expect(me).toBeDisabled()
      fireEvent.click(me)
    }
    fireEvent.click(screen.getByRole('button', { name: 'Speaker says 姐' }))
    expect(calls).toEqual(['speaker 2'])
  })
})
