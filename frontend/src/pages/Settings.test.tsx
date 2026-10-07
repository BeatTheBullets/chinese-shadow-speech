import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import Settings from './Settings'

describe('<Settings> YouTube', () => {
  afterEach(cleanup)
  it('offers the bookmarklet for this origin', () => {
    render(<Settings />)
    const link = screen.getByRole('link', { name: '→ shadow-speech' })
    expect(link.getAttribute('href')).toBe(`javascript:location.href='${window.location.origin}/library?add='+encodeURIComponent(location.href)`)
  })
})
