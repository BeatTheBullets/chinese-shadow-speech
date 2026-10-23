import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Transport from './Transport'

const sound = { rate: 1, onRate: () => {}, volume: { reference: 0.8, guide: null, onReference: () => {}, onGuide: () => {} } }
const props = { onAction: () => {}, idx: 0, total: 3, recording: false, busy: false, hint: '', error: '', sound }

describe('<Transport>', () => {
  afterEach(cleanup)

  it('› is disabled with canNext false (Practice\'s last sentence), and enabled by default', () => {
    const onAction = vi.fn()
    const { rerender } = render(<Transport {...props} idx={2} onAction={onAction} />)
    expect(screen.getByRole('button', { name: 'Next sentence (→)' })).toBeEnabled()
    rerender(<Transport {...props} idx={2} onAction={onAction} canNext={false} />)
    const next = screen.getByRole('button', { name: 'Next sentence (→)' })
    expect(next).toBeDisabled()
    fireEvent.click(next)
    expect(onAction).not.toHaveBeenCalled()
  })

  it('the Sound button says whether its pop-up is open', () => {
    render(<Transport {...props} />)
    const btn = screen.getByRole('button', { name: 'Sound' })
    expect(btn).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(btn)
    expect(btn).toHaveAttribute('aria-expanded', 'true')
  })
  it('pulse marks the next expected action: Record, or › to move on; never Stop', () => {
    const rec = () => screen.getByRole('button', { name: /^(Record|Stop) \(Enter\)$/ }), next = () => screen.getByRole('button', { name: 'Next sentence (→)' })
    const { rerender } = render(<Transport {...props} pulse="record" />)
    expect(rec()).toHaveClass('pulse-next')
    expect(next()).not.toHaveClass('pulse-next')
    rerender(<Transport {...props} pulse="next" />)
    expect(next()).toHaveClass('pulse-next')
    expect(rec()).not.toHaveClass('pulse-next')
    rerender(<Transport {...props} pulse="record" recording />)
    expect(rec()).not.toHaveClass('pulse-next')
    rerender(<Transport {...props} />)
    expect(rec()).not.toHaveClass('pulse-next')
    expect(next()).not.toHaveClass('pulse-next')
  })
  it('replaying: Enter is "■ Stop replay", in the plain button look, not record red', () => {
    const onAction = vi.fn()
    render(<Transport {...props} replaying pulse="record" onAction={onAction} />)
    const stop = screen.getByRole('button', { name: 'Stop replay (Enter)' })
    expect(stop).not.toHaveClass('bg-record')
    expect(stop).toHaveClass('bg-card')
    expect(stop).not.toHaveClass('pulse-next')
    expect(stop.querySelector('svg')).not.toBeNull()
    expect(screen.queryByRole('button', { name: /^Record/ })).toBeNull()
    fireEvent.click(stop)
    expect(onAction).toHaveBeenCalledWith('record')
  })
})
