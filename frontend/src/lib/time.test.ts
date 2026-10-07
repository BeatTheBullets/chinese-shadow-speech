import { describe, expect, it } from 'vitest'
import { mmss } from './time'

describe('mmss', () => {
  it('formats seconds as mm:ss', () => { expect(mmss(0)).toBe('00:00'); expect(mmss(83.6)).toBe('01:23'); expect(mmss(3725)).toBe('62:05') })
})
