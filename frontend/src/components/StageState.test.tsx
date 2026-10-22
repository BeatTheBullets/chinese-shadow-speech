import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import StageState from './StageState'

const card = <p data-testid="card">你好</p>

// The take timer reads the performance clock and ticks on its own interval: fake both.
beforeEach(() => { vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'performance'] }) })
afterEach(() => { cleanup(); vi.useRealTimers() })
const ago = (s: number) => performance.now() / 1000 - s   // a startedAt `s` seconds back on the performance clock

describe('<StageState>', () => {

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
    render(<StageState stage="yourTurn" startedAt={ago(2.7)}>{card}</StageState>)
    expect(screen.getByTestId('stage')).toHaveClass('border-record')
    expect(screen.getByText('Your turn')).toHaveClass('text-3xl')
    expect(screen.getByTestId('rec-dot')).toHaveClass('animate-pulse')
    expect(screen.getByTestId('rec-timer')).toHaveTextContent('0:02')
  })
  it('the timer counts minutes past 59 s', () => {
    render(<StageState stage="yourTurn" startedAt={ago(75)}>{card}</StageState>)
    expect(screen.getByTestId('rec-timer')).toHaveTextContent('1:15')
  })
  it('along: the same frame, dot and timer, saying "Speak along"', () => {
    render(<StageState stage="along" startedAt={ago(0)}>{card}</StageState>)
    expect(screen.getByTestId('stage')).toHaveClass('border-record')
    expect(screen.getByText('Speak along')).toBeInTheDocument()
    expect(screen.getByTestId('rec-dot')).toBeInTheDocument()
    expect(screen.getByTestId('rec-timer')).toHaveTextContent('0:00')
  })
  it('along with a count: the speak-along frame stays and the 3·2·1 ring shows inside it', () => {
    render(<StageState stage="along" count={2} startedAt={ago(5)}>{card}</StageState>)
    expect(screen.getByTestId('stage')).toHaveClass('border-record')
    expect(screen.getByText('Speak along')).toBeInTheDocument()
    expect(screen.getByTestId('rec-timer')).toHaveTextContent('0:05')
    expect(screen.getByLabelText('starting in 2')).toHaveTextContent('2')
  })
  it('the timer ticks by itself from startedAt, a few times a second, and stops ticking once unmounted', () => {
    const { unmount } = render(<StageState stage="yourTurn" startedAt={ago(0)}>{card}</StageState>)
    expect(screen.getByTestId('rec-timer')).toHaveTextContent('0:00')
    act(() => { vi.advanceTimersByTime(1250) })
    expect(screen.getByTestId('rec-timer')).toHaveTextContent('0:01')
    act(() => { vi.advanceTimersByTime(61000) })
    expect(screen.getByTestId('rec-timer')).toHaveTextContent('1:02')
    unmount()
    expect(vi.getTimerCount()).toBe(0)
  })
  it('autoStop (Echo, Drill) adds the small "stops by itself when you finish" beside the timer; Flow has none', () => {
    const { rerender } = render(<StageState stage="yourTurn" startedAt={ago(2)} autoStop>{card}</StageState>)
    expect(screen.getByText('stops by itself when you finish')).toHaveClass('text-fgdim')
    rerender(<StageState stage="along" startedAt={ago(2)}>{card}</StageState>)
    expect(screen.queryByText('stops by itself when you finish')).toBeNull()
    rerender(<StageState stage="idle" autoStop note="Ready">{card}</StageState>)
    expect(screen.queryByText('stops by itself when you finish')).toBeNull()
  })
  it('the cue area keeps one min-height in every stage, so nothing below it moves', () => {
    const minH = () => [...screen.getByTestId('stage-cue').classList].filter((c) => c.startsWith('min-h-'))
    const { rerender } = render(<StageState stage="idle" note="Ready">{card}</StageState>)
    const want = minH()
    expect(want).toHaveLength(1)
    for (const [stage, count] of [['listen', null], ['getReady', 3], ['yourTurn', null], ['along', null], ['along', 2], ['review', null]] as const) {
      rerender(<StageState stage={stage} count={count} startedAt={ago(1)} note="n">{card}</StageState>)
      expect(minH(), stage).toEqual(want)
    }
  })
  it('the countdown ring is overlaid (absolute) in getReady and inside along, so it pushes nothing down', () => {
    const { rerender } = render(<StageState stage="getReady" count={3}>{card}</StageState>)
    expect(screen.getByTestId('countdown')).toHaveClass('absolute')
    rerender(<StageState stage="along" count={2} startedAt={ago(1)}>{card}</StageState>)
    expect(screen.getByTestId('countdown')).toHaveClass('absolute')
    expect(screen.getByTestId('stage-cue')).toContainElement(screen.getByTestId('countdown'))
  })
  it('the live waveform has a fixed slot, held empty outside the speaking stages', () => {
    const wave = <div data-testid="w" />
    const { rerender } = render(<StageState stage="listen" wave={wave}>{card}</StageState>)
    expect(screen.getByTestId('wave-slot')).toHaveClass('h-12')
    expect(screen.queryByTestId('w')).toBeNull()
    rerender(<StageState stage="yourTurn" startedAt={ago(0)} wave={wave}>{card}</StageState>)
    expect(screen.getByTestId('wave-slot')).toHaveClass('h-12')
    expect(screen.getByTestId('wave-slot')).toContainElement(screen.getByTestId('w'))
    rerender(<StageState stage="idle">{card}</StageState>)
    expect(screen.queryByTestId('wave-slot')).toBeNull()      // a stage without a mic (the Flow summary) keeps no slot
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
  it('compact (Flow): one smaller min-height that still holds the ring, a smaller wave slot, and the ring beside "Get ready"', () => {
    const minH = () => [...screen.getByTestId('stage-cue').classList].filter((c) => c.startsWith('min-h-'))
    const { rerender } = render(<StageState compact stage="getReady" count={3} wave={<div />}>{card}</StageState>)
    expect(minH()).toEqual(['min-h-20'])                         // the ring is h-20 (80 px): nothing taller
    expect(screen.getByTestId('wave-slot')).toHaveClass('h-10')
    expect(screen.getByTestId('countdown')).toHaveClass('absolute', 'right-1/2')
    expect(screen.getByText('Get ready')).toHaveClass('left-1/2')
    for (const [stage, count] of [['idle', null], ['listen', null], ['yourTurn', null], ['along', 2]] as const) {
      rerender(<StageState compact stage={stage} count={count} startedAt={ago(1)} wave={<div />}>{card}</StageState>)
      expect(minH(), stage).toEqual(['min-h-20'])
    }
  })
})
