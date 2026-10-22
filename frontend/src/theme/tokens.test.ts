import { describe, it, expect } from 'vitest'
import { TOKENS, WIPE_FILL, contrast, multiply } from './tokens'

describe('tokens', () => {
  it('tokens match the spec', () => {
    expect(TOKENS).toEqual({
      bg: '#2b0510', panel: '#3d0a1b', card: '#4E001B', line: '#6b1a33',
      fg: '#f6ead8', fgdim: '#c7a9a0', accent: '#F5CB00', ref: '#d6e6ea', you: '#F5CB00',
      ok: '#2bae85', warn: '#f0a020', bad: '#ff5a3c', sound: '#cca4e3', record: '#cb2c1b',
    })
  })
  it('text pairs meet AA', () => {
    for (const fg of ['fg', 'fgdim', 'accent', 'ref', 'ok', 'warn', 'bad', 'sound'] as const)
      for (const bg of ['bg', 'panel', 'card'] as const)
        expect(contrast(TOKENS[fg], TOKENS[bg]), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5)
  })
})

it('fg text on the record button meets AA', () => {
  expect(contrast(TOKENS.fg, TOKENS.record)).toBeGreaterThanOrEqual(4.5)
})

describe('karaoke wipe fills', () => {
  it('multiply is the channel-wise product', () => {
    expect(multiply('#ffffff', '#8fb3d9')).toBe('#8fb3d9')
    expect(multiply('#808080', '#000000')).toBe('#000000')
    expect(multiply('#f6ead8', '#ffffff')).toBe('#f6ead8')
  })
  it('the Listen wipe turns fg clearly blue-grey: >= 2:1 against the unwiped text', () => {
    const wiped = multiply(TOKENS.fg, WIPE_FILL.ref)
    expect(contrast(wiped, TOKENS.fg)).toBeGreaterThanOrEqual(2)
    const [r, , b] = [1, 3, 5].map((i) => parseInt(wiped.slice(i, i + 2), 16))
    expect(b).toBeGreaterThan(r)                       // blue over red: a cool shift of the warm fg, not just darker
    expect(contrast(multiply(TOKENS.fg, TOKENS.ref), TOKENS.fg)).toBeLessThan(2) // why ref itself is not the fill
  })
  it('the ghost wipe turns fg you-gold: the blue channel goes, and it is darker than the 55% fill was', () => {
    const wiped = multiply(TOKENS.fg, WIPE_FILL.ghost)
    expect(parseInt(wiped.slice(5, 7), 16)).toBe(0)
    expect(contrast(wiped, TOKENS.fg)).toBeGreaterThanOrEqual(1.5)
  })
})
