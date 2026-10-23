import { render } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Waveform from './Waveform'

// jsdom has no 2D context: record what the component draws.
function mockCtx(withRoundRect: boolean) {
  const log: { op: string; alpha: number; x?: number; h?: number }[] = []
  const g: Record<string, unknown> = { globalAlpha: 1, fillStyle: '', strokeStyle: '' }
  const rec = (op: string) => (x?: number, _y?: number, _w?: number, h?: number) => { log.push({ op, alpha: g.globalAlpha as number, x, h }) }
  for (const op of ['clearRect', 'fillRect', 'beginPath', 'moveTo', 'lineTo', 'stroke']) g[op] = rec(op)
  if (withRoundRect) { g.roundRect = rec('roundRect'); g.fill = rec('fill') }
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(g as unknown as CanvasRenderingContext2D)
  return log
}
afterEach(() => vi.restoreAllMocks())

const peaks = new Float32Array([0.5, 0.5, 0.5, 0.5])
// 4 bars over 40 px: bar i starts at x = 10 i; playhead at 1.5 s * 20 px/s = 30 -> bars 0..2 played.
const props = { peaks, duration: 2, pxPerSec: 20, color: '#fff', playhead: 1.5 }

describe('Waveform', () => {
  it('played bars full, unplayed at 0.35', () => {
    const log = mockCtx(true)
    render(<Waveform {...props} />)
    const bars = log.filter((l) => l.op === 'roundRect')
    expect(bars.map((b) => b.alpha)).toEqual([1, 1, 1, 0.35])
  })
  it('bars are rounded', () => {
    const log = mockCtx(true)
    render(<Waveform {...props} />)
    expect(log.some((l) => l.op === 'roundRect')).toBe(true)
  })
  it('falls back to fillRect when roundRect is missing', () => {
    const log = mockCtx(false)
    render(<Waveform {...props} />)
    expect(log.filter((l) => l.op === 'fillRect').map((b) => b.alpha)).toEqual([1, 1, 1, 0.35])
  })
  it('ticks are drawn at half opacity, playhead at full', () => {
    const log = mockCtx(true)
    render(<Waveform {...props} ticks={[1]} />)
    const strokes = log.filter((l) => l.op === 'stroke').map((l) => l.alpha)
    expect(strokes).toEqual([0.5, 1])
  })
  it('scales the bars to the track\'s own peak: a quiet take draws as tall as a loud one, the loudest bar full height', () => {
    const heights = (p: number[]) => {
      const log = mockCtx(true)
      render(<Waveform {...props} peaks={Float32Array.from(p)} height={36} />)
      const hs = log.filter((l) => l.op === 'roundRect').map((l) => l.h!)
      vi.restoreAllMocks()
      return hs
    }
    const loud = heights([0.2, 0.8, 0.4, 0.1]), quiet = heights([0.01, 0.04, 0.02, 0.005])
    expect(quiet).toHaveLength(4)
    quiet.forEach((h, i) => expect(h).toBeCloseTo(loud[i], 4))
    expect(Math.max(...loud)).toBeCloseTo(36 - 4, 6)
  })
})
