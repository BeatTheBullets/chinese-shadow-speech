import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { METER_MS } from '../audio/useMicLevel'
import CueLine, { WithMicLevel } from './CueLine'

describe('<WithMicLevel>', () => {
  afterEach(() => { cleanup(); vi.useRealTimers() })

  it('polls the mic level itself and re-renders only its children', () => {
    vi.useFakeTimers()
    let v: number | null = null
    const mic = { level: () => v }
    const renders = vi.fn()
    function Parent() { renders(); return <WithMicLevel mic={mic}>{(level) => <CueLine cue={{ icon: '🎤', text: 'Speak along', tone: 'you' }} level={level} />}</WithMicLevel> }
    render(<Parent />)
    expect(screen.queryByRole('meter')).toBeNull()
    v = 0.2
    act(() => { vi.advanceTimersByTime(METER_MS) })
    expect(screen.getByRole('meter', { name: 'Microphone level' })).toHaveAttribute('aria-valuenow', String(Math.min(1, 0.2 * 3)))
    v = 0.1
    act(() => { vi.advanceTimersByTime(METER_MS) })
    expect(screen.getByRole('meter')).toHaveAttribute('aria-valuenow', String(0.1 * 3))
    expect(renders).toHaveBeenCalledTimes(1)
  })
})
