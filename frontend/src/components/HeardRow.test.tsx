import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Cell } from '../lib/cells'
import HeardRow from './HeardRow'

const base: Cell[] = [['她', 'tā'], ['喜', 'xǐ'], ['欢', 'huān'], ['吃', 'chī'], ['苹', 'píng'], ['果', 'guǒ']].map(([ch, pinyin]) => ({ ch, pinyin, tone: 1 }))

describe('<HeardRow>', () => {
  it('shows only the slipped syllables, aligned', () => {
    const cells = base.map((c, i) => (i === 3 ? { ...c, heardSound: 'cī' } : i === 4 ? { ...c, heardSound: 'pín' } : c))
    const { container } = render(<HeardRow cells={cells} />)
    expect(screen.getByText('HEARD')).toBeInTheDocument()
    const slots = container.querySelectorAll('[data-slot]')
    expect(slots).toHaveLength(6)
    expect(Array.from(slots).map((s) => s.textContent)).toEqual(['', '', '', 'cī', 'pín', ''])
    expect(screen.getByText('cī')).toHaveClass('text-sound', 'font-semibold')
    expect(slots[3]).toHaveAttribute('title', 'heard cī instead of chī')
    expect(slots[3]).toHaveClass('border-dashed', 'border-sound')
    // 24 px slot - 2 px border - 4 px padding leaves 18 px for a 16 px line of 11 px text: nothing clipped
    expect(slots[3]).toHaveClass('h-6', 'py-0.5', 'w-12'); expect(screen.getByText('cī')).toHaveClass('text-[11px]', 'leading-4')
  })
  it('renders nothing without slips', () => {
    const { container } = render(<HeardRow cells={base} />)
    expect(container).toBeEmptyDOMElement()
  })
})
