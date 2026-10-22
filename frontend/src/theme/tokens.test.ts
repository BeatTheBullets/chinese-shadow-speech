import { describe, it, expect } from 'vitest'
import { TOKENS, contrast } from './tokens'

describe('tokens', () => {
  it('tokens match the spec', () => {
    expect(TOKENS).toEqual({
      bg: '#2b0510', panel: '#3d0a1b', card: '#4E001B', line: '#6b1a33',
      fg: '#f6ead8', fgdim: '#c7a9a0', accent: '#F5CB00', ref: '#d6e6ea', you: '#F5CB00',
      ok: '#2bae85', warn: '#f0a020', bad: '#ff5a3c', sound: '#cca4e3', record: '#e0301e',
    })
  })
  it('text pairs meet AA', () => {
    for (const fg of ['fg', 'fgdim', 'accent', 'ref', 'ok', 'warn', 'bad', 'sound'] as const)
      for (const bg of ['bg', 'panel', 'card'] as const)
        expect(contrast(TOKENS[fg], TOKENS[bg]), `${fg} on ${bg}`).toBeGreaterThanOrEqual(4.5)
  })
})
