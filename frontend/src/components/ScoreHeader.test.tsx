import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Score } from '../api/types'
import ScoreHeader from './ScoreHeader'

const s = (o: Partial<Score>): Score => ({ overall: 0.82, tone_overall: 0.82, segmental_overall: null, rate_ratio: 1.1, ref_contour: null, usr_contour: null, syllables: [], warnings: [], ...o })

describe('<ScoreHeader>', () => {
  it('shows overall, tone, segmental placeholder, best and attempts', () => {
    render(<ScoreHeader score={s({})} best={0.9} attempts={3} />)
    expect(screen.getByTestId('overall')).toHaveTextContent('82')
    expect(screen.getByText('tone 82')).toBeInTheDocument()
    expect(screen.getByText('segmental · Phase 3')).toBeInTheDocument()
    expect(screen.getByText('best 90')).toBeInTheDocument()
    expect(screen.getByText('3 attempts')).toBeInTheDocument()
  })
  it('shows the gate warning instead of a score', () => {
    render(<ScoreHeader score={s({ overall: null, tone_overall: null, warnings: ['too_short'] })} best={null} attempts={1} />)
    expect(screen.getByText(/Too short — not scored/)).toBeInTheDocument()
    expect(screen.queryByTestId('overall')).toBeNull()
  })
  it('shortens a long heard text in the header', () => {
    const heard = '一二三四五六七八九十一二三四五六七八九十一二三四五六七八九十'
    render(<ScoreHeader score={s({ overall: null, tone_overall: null, warnings: ['different_words'], heard_text: heard })} best={null} attempts={1} />)
    expect(screen.getByText(`Heard different words — not scored. Heard: ${heard.slice(0, 24)}…`)).toBeInTheDocument()
  })
  it('says nothing is scored yet without a take', () => {
    render(<ScoreHeader score={undefined} best={null} attempts={0} />)
    expect(screen.getByText('no score yet')).toBeInTheDocument()
  })
})
