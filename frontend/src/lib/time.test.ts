import { describe, expect, it } from 'vitest'
import { mmss, weekdayTime } from './time'

describe('mmss', () => {
  it('formats seconds as mm:ss', () => { expect(mmss(0)).toBe('00:00'); expect(mmss(83.6)).toBe('01:23'); expect(mmss(3725)).toBe('62:05') })
})

describe('weekdayTime', () => {
  it("shows an instant as weekday and 24-hour time in the user's time zone", () => {
    expect(weekdayTime(new Date(2026, 9, 7, 9, 5).toISOString())).toBe('Wed 09:05')
    expect(weekdayTime(new Date(2026, 9, 11, 21, 40).toISOString())).toBe('Sun 21:40')
  })
})
