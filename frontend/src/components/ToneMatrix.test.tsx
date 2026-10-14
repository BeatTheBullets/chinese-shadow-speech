import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import ToneMatrix from './ToneMatrix'

describe('<ToneMatrix>', () => {
  it('lays pairs out previous tone × tone, dims thin cells', () => {
    render(<ToneMatrix pairs={[{ prev_tone: 3, tone: 2, mean: 0.42, n: 3 }, { prev_tone: 1, tone: 4, mean: 0.9, n: 12 }]} />)
    const thin = screen.getByTitle('after tone 3, tone 2: 42 (n 3)')
    expect(thin).toHaveTextContent('42'); expect(thin).toHaveClass('cell-bad'); expect(thin).toHaveClass('opacity-40')
    expect(screen.getByTitle('after tone 1, tone 4: 90 (n 12)')).toHaveClass('cell-ok')
    expect(screen.getAllByText('·')).toHaveLength(23)
  })
})
