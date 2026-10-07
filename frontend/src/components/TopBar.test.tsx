import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'
import TopBar from './TopBar'

describe('<TopBar>', () => {
  it('each mode tab explains the mode on hover, and ? opens the help', () => {
    const onHelp = vi.fn()
    render(<MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <TopBar title="L" speaker="" idx={0} total={2} mode="echo" onMode={() => {}} elapsedS={0} chorusPasses={5} onHelp={onHelp} />
    </MemoryRouter>)
    expect(screen.getByRole('button', { name: 'Echo' })).toHaveAttribute('title', 'One sentence at a time: listen, then repeat it on your own. You hear the original and your take back to back.')
    expect(screen.getByRole('button', { name: 'Chorus' })).toHaveAttribute('title', 'Speak at the same time as the sentence, 5 times in a row. Only the last pass is recorded.')
    expect(screen.getByRole('button', { name: 'Flow' }).title).toMatch(/^Shadow a whole passage without stopping\./)
    expect(screen.getByRole('button', { name: 'Guided' }).title).toMatch(/^Four steps per sentence:/)
    screen.getByRole('button', { name: 'Help' }).click()
    expect(onHelp).toHaveBeenCalled()
  })
})
