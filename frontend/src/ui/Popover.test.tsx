import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import Popover from './Popover'

const setup = (onClose = vi.fn()) => {
  render(<div><button>outside</button><Popover open onClose={onClose} anchor={<button>Sound</button>}><button>inner</button></Popover></div>)
  return onClose
}

describe('Popover', () => {
  it('closes on Esc and outside click', () => {
    const onClose = setup()
    fireEvent.keyDown(screen.getByText('inner'), { key: 'Escape' })
    expect(onClose).toHaveBeenCalledTimes(1)
    fireEvent.pointerDown(screen.getByText('inner'))
    expect(onClose).toHaveBeenCalledTimes(1)
    fireEvent.pointerDown(screen.getByText('outside'))
    expect(onClose).toHaveBeenCalledTimes(2)
  })
  it('does not swallow Space/Enter', () => {
    setup()
    const seen: string[] = []
    const h = (e: KeyboardEvent) => seen.push(e.key)
    window.addEventListener('keydown', h)
    screen.getByText('inner').focus()
    fireEvent.keyDown(screen.getByText('inner'), { key: ' ' })
    fireEvent.keyDown(screen.getByText('inner'), { key: 'Enter' })
    window.removeEventListener('keydown', h)
    expect(seen).toEqual([' ', 'Enter'])
  })
  it('is not a dialog', () => {
    setup()
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole('group')).toBeTruthy()
  })
  it('renders nothing but the anchor when closed', () => {
    render(<Popover open={false} onClose={() => {}} anchor={<span>a</span>}><i>body</i></Popover>)
    expect(screen.queryByText('body')).toBeNull()
  })
})
