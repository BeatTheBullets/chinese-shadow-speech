import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import StageState from './StageState'

const card = <p data-testid="card">你好</p>

describe('<StageState>', () => {
  afterEach(cleanup)

  it('idle: the stage as it is, with the small note saying what Enter does; no frame', () => {
    render(<StageState stage="idle" note="Ready — Enter to start">{card}</StageState>)
    expect(screen.getByTestId('stage')).toContainElement(screen.getByTestId('card'))
    expect(screen.getByText('Ready — Enter to start')).toBeInTheDocument()
    expect(screen.getByTestId('stage')).not.toHaveClass('border-record')
  })
  it('listen: a small, calm "▶ Listening" label in the speaker colour', () => {
    render(<StageState stage="listen">{card}</StageState>)
    const label = screen.getByRole('status')
    expect(label).toHaveTextContent('▶ Listening')
    expect(label).toHaveClass('text-ref')
    expect(screen.getByTestId('stage')).not.toHaveClass('border-record')
  })
  it('getReady: a big count in accent inside a ring that runs down, plus "Get ready"', () => {
    const { rerender } = render(<StageState stage="getReady" count={3}>{card}</StageState>)
    const ring = screen.getByLabelText('starting in 3')
    expect(ring).toHaveTextContent('3')
    expect(ring).toHaveClass('text-accent')
    expect(screen.getByText('Get ready')).toBeInTheDocument()
    const arc = () => Number(screen.getByTestId('countdown-arc').getAttribute('stroke-dashoffset'))
    const full = arc()
    rerender(<StageState stage="getReady" count={1}>{card}</StageState>)
    expect(screen.getByLabelText('starting in 1')).toHaveTextContent('1')
    expect(arc()).toBeGreaterThan(full) // less of the ring left
    expect(screen.getByTestId('stage')).not.toHaveClass('border-record')
    expect(screen.queryByText('●')).toBeNull() // no dots any more
  })
  it('yourTurn: the record frame, large "Your turn", a pulsing red dot and an m:ss timer', () => {
    render(<StageState stage="yourTurn" recordingS={2.7}>{card}</StageState>)
    expect(screen.getByTestId('stage')).toHaveClass('border-record')
    expect(screen.getByText('Your turn')).toHaveClass('text-3xl')
    expect(screen.getByTestId('rec-dot')).toHaveClass('animate-pulse')
    expect(screen.getByTestId('rec-timer')).toHaveTextContent('0:02')
  })
  it('the timer counts minutes past 59 s', () => {
    render(<StageState stage="yourTurn" recordingS={75}>{card}</StageState>)
    expect(screen.getByTestId('rec-timer')).toHaveTextContent('1:15')
  })
  it('along: the same frame, dot and timer, saying "Speak along"', () => {
    render(<StageState stage="along" recordingS={0}>{card}</StageState>)
    expect(screen.getByTestId('stage')).toHaveClass('border-record')
    expect(screen.getByText('Speak along')).toBeInTheDocument()
    expect(screen.getByTestId('rec-dot')).toBeInTheDocument()
    expect(screen.getByTestId('rec-timer')).toHaveTextContent('0:00')
  })
  it('along with a count: the speak-along frame stays and the 3·2·1 ring shows inside it', () => {
    render(<StageState stage="along" count={2} recordingS={5}>{card}</StageState>)
    expect(screen.getByTestId('stage')).toHaveClass('border-record')
    expect(screen.getByText('Speak along')).toBeInTheDocument()
    expect(screen.getByTestId('rec-timer')).toHaveTextContent('0:05')
    expect(screen.getByLabelText('starting in 2')).toHaveTextContent('2')
  })
  it('yourTurn ignores a count: no ring once it is your turn', () => {
    render(<StageState stage="yourTurn" count={2}>{card}</StageState>)
    expect(screen.queryByTestId('countdown')).toBeNull()
  })
  it('review: the original, then you, in the speaker colour; the note stays', () => {
    render(<StageState stage="review" note="Scoring…">{card}</StageState>)
    expect(screen.getByText('Listen — the original, then you')).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveClass('text-ref')
    expect(screen.getByText('Scoring…')).toBeInTheDocument()
    expect(screen.getByTestId('stage')).not.toHaveClass('border-record')
  })
  it('the moment to speak carries no note: nothing competes with "Your turn"', () => {
    render(<StageState stage="yourTurn" note="Ready — Enter to start">{card}</StageState>)
    expect(screen.queryByText('Ready — Enter to start')).toBeNull()
  })
})
