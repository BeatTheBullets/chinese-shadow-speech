import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Contour } from '../api/types'
import PitchLine from '../components/PitchLine'
import { contourPoints, pathOf, pitchRange, warpPoints } from './pitch'

const c: Contour = { t0_s: 0.1, step_ms: 10, f0_st: [0, 1, null, 2], spans: [[0.1, 0.12], [0.12, 0.14]] }

describe('pitch', () => {
  it('turns a contour into timed points', () => {
    expect(contourPoints(c)).toEqual([[0.1, 0], [0.11, 1], [0.12, null], [0.13, 2]].map(([t, v]) => [expect.closeTo(t as number, 9), v]))
  })
  it('warps each reference syllable onto the learner span, breaking between syllables', () => {
    const pts = warpPoints(c, [[1.0, 1.4], [1.4, 2.0]])
    expect(pts[0][0]).toBeCloseTo(1.0); expect(pts[0][1]).toBe(0)
    expect(pts[1][0]).toBeCloseTo(1.2); expect(pts[1][1]).toBe(1)
    expect(pts[2][1]).toBeNull()                                  // syllable break
    expect(pts.at(-1)![0]).toBeCloseTo(1.4 + 0.3)                  // frame 0.13 is halfway through the second span
  })
  it('range is padded and never collapses', () => {
    expect(pitchRange([[0, 1], [1, 1]])).toEqual([0, 2])
    const [lo, hi] = pitchRange([[0, -2], [1, 3]], [[0, null]])
    expect(lo).toBeCloseTo(-2.5); expect(hi).toBeCloseTo(3.5)
  })
  it('path breaks at nulls and maps higher pitch up', () => {
    const d = pathOf([[0, 0], [1, 2], [2, null], [3, 0]], 10, 40, [0, 2])
    expect(d).toBe('M0.0,40.0L10.0,0.0M30.0,40.0')
  })
  it('PitchLine draws one path per series', () => {
    const { container } = render(<PitchLine series={[{ points: [[0, 0], [1, 1]], className: 'a' }, { points: [], className: 'b' }]} pxPerSec={10} duration={1} height={44} range={[0, 1]} />)
    expect(container.querySelectorAll('path')).toHaveLength(2)
  })
})
