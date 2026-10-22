import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { TOKENS, contrast } from '../theme/tokens'
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
  const HINT = { default: 'text-fgdim', ghost: 'text-fgdim', record: 'text-fg', primary: 'text-bg' } as const
  const BG = { default: 'card', ghost: 'bg', record: 'record', primary: 'accent' } as const
  const HEX = (cls: string) => TOKENS[cls.replace('text-', '') as keyof typeof TOKENS]
  it.each(['default', 'ghost', 'record', 'primary'] as const)('%s variant hint colour class and AA contrast', v => {
    render(<Button label="L" keyHint="K" variant={v} onClick={() => {}} />)
    expect(screen.getByText('K').classList.contains(HINT[v])).toBe(true)
    expect(contrast(HEX(HINT[v]), TOKENS[BG[v]])).toBeGreaterThanOrEqual(4.5)
  })
  it('the default variant sits on card, the button surface (spec §1.1)', () => {
    render(<Button label="L" onClick={() => {}} />)
    expect(screen.getByRole('button')).toHaveClass('bg-card')
  })
  it('ariaExpanded reaches aria-expanded; without it there is none', () => {
    const { rerender } = render(<Button label="Sound" ariaExpanded={false} onClick={() => {}} />)
    expect(screen.getByRole('button')).toHaveAttribute('aria-expanded', 'false')
    rerender(<Button label="Sound" ariaExpanded onClick={() => {}} />)
    expect(screen.getByRole('button')).toHaveAttribute('aria-expanded', 'true')
    rerender(<Button label="Sound" onClick={() => {}} />)
    expect(screen.getByRole('button')).not.toHaveAttribute('aria-expanded')
  })
})
