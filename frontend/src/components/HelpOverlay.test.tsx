import { cleanup, fireEvent, render, screen } from '@testing-library/react'
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

  it('lists the keys ← → Space Enter R A S F T P E L ? each as a key cap, and not C', () => {
    render(<HelpOverlay onClose={() => {}} />)
    const caps = [...screen.getByRole('dialog').querySelectorAll('kbd')].map((k) => k.textContent)
    expect([...caps].sort()).toEqual(['←', '→', 'Space', 'Enter', 'R', 'A', 'S', 'F', 'T', 'P', 'E', 'L', '?'].sort())
    expect(caps).not.toContain('C')
  })
})
