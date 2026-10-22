import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import Button from './Button'

describe('Button', () => {
  it('shows the key hint under the label, not as the face', () => {
    render(<Button label="Listen" keyHint="Space" onClick={() => {}} />)
    expect(screen.getByText('Listen')).toBeTruthy()
    const hint = screen.getByText('Space')
    expect(hint.classList.contains('text-fgdim')).toBe(true)
    expect(hint.classList.contains('text-[9px]')).toBe(true)
  })
  it('aria-label includes the key', () => {
    render(<Button label="Listen" keyHint="Space" onClick={() => {}} />)
    expect(screen.getByRole('button').getAttribute('aria-label')).toBe('Listen (Space)')
  })
})
