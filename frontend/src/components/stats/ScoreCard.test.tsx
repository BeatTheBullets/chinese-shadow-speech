import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import ScoreCard from './ScoreCard'

const wrap = (ui: React.ReactElement) => render(<MemoryRouter>{ui}</MemoryRouter>)

describe('<ScoreCard>', () => {
  it('shows a dash and the count when there is no score', () => {
    wrap(<ScoreCard title="Tones" score={{ value: null, last7: null, prev7: null, n: 12 }} unit="syllables" how="how" to="/stats/tones" />)
    expect(screen.getByText('—', { selector: '[data-score]' })).toBeInTheDocument()
    expect(screen.getByText('12 syllables')).toBeInTheDocument()
  })
  it('shows the score, the change, the how text and links to the details page', () => {
    wrap(<ScoreCard title="Tones" score={{ value: 0.62, last7: 0.7, prev7: 0.6, n: 312 }} unit="syllables" how="Your average tone score" to="/stats/tones" />)
    expect(screen.getByText('62')).toBeInTheDocument()
    expect(screen.getByText('▲ 10')).toBeInTheDocument()
    expect(screen.getByText(/vs last week/)).toBeInTheDocument()
    expect(screen.getByText('Your average tone score')).toBeInTheDocument()
    expect(screen.getByRole('link')).toHaveAttribute('href', '/stats/tones')
  })
})
