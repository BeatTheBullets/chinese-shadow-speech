import { cleanup, fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import HelpOverlay from './HelpOverlay'

describe('<HelpOverlay>', () => {
  const later = vi.fn()
  afterEach(() => { cleanup(); window.removeEventListener('keydown', later); later.mockClear() })

  it('? and Esc close it and reach no window listener added after it (the page shortcuts)', () => {
    const onClose = vi.fn()
    render(<HelpOverlay onClose={onClose} />)
    window.addEventListener('keydown', later)
    fireEvent.keyDown(window, { key: '?' })
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(2)
    expect(later).not.toHaveBeenCalled()
  })

  it('ignores an auto-repeated ? or Esc', () => {
    const onClose = vi.fn()
    render(<HelpOverlay onClose={onClose} />)
    fireEvent.keyDown(window, { key: '?', repeat: true })
    fireEvent.keyDown(window, { key: 'Escape', repeat: true })
    expect(onClose).not.toHaveBeenCalled()
  })
})
