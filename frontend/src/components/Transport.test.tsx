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
})
