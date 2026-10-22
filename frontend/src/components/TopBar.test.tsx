import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import TopBar from './TopBar'

describe('<TopBar>', () => {
  it('each mode tab explains the mode on hover, and ? opens the help', () => {
    const onHelp = vi.fn()
    render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <TopBar title="L" speaker="" mode="echo" onMode={() => {}} elapsedS={0} onHelp={onHelp} />
    </MemoryRouter>)
    expect(screen.getByRole('button', { name: 'Echo' })).toHaveAttribute('title', 'One sentence at a time: listen, then repeat it on your own. You hear the original and your take back to back.')
    expect(screen.getByRole('button', { name: 'Flow' }).title).toMatch(/^Shadow a whole passage without stopping\./)
    screen.getByRole('button', { name: 'Help' }).click()
    expect(onHelp).toHaveBeenCalled()
  })

  it('offers only Echo and Flow', () => {
    render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <TopBar title="L" speaker="" mode="echo" onMode={() => {}} elapsedS={0} onHelp={() => {}} />
    </MemoryRouter>)
    const modes = screen.getAllByRole('button').filter((b) => b.getAttribute('aria-label') !== 'Help').map((b) => b.textContent)
    expect(modes).toEqual(['Echo', 'Flow'])
  })

  it('the way home is a visible Library button that keeps its back handler', () => {
    const onBack = vi.fn((e: { preventDefault: () => void }) => e.preventDefault())
    render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <TopBar title="L" speaker="" mode="echo" onMode={() => {}} elapsedS={0} onHelp={() => {}} onBack={onBack} />
    </MemoryRouter>)
    const home = screen.getByRole('link', { name: 'Back to the library' })
    expect(home).toHaveTextContent('⌂ Library')
    expect(home).toHaveAttribute('title', 'Back to the library')
    expect(home).toHaveAttribute('href', '/library')
    expect(home.className).toContain('btn')
    fireEvent.click(home)
    expect(onBack).toHaveBeenCalledTimes(1)
  })
})
