import { act, cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { LIVE_WINDOW_S } from '../audio/pcm'
import LiveWave, { WAVE_BARS, WAVE_MS } from './LiveWave'

// A window of `WAVE_BARS` 20 ms frames (here 10 samples each) at a constant amplitude: its RMS is `amp`.
const frames = (amp: number) => new Float32Array(WAVE_BARS * 10).fill(amp)
const heights = () => screen.queryAllByTestId('wave-bar').map((b) => parseFloat((b as HTMLElement).style.height))

describe('<LiveWave>', () => {
  beforeEach(() => { vi.useFakeTimers() })
  afterEach(() => { cleanup(); vi.useRealTimers() })

  it('one bar per 20 ms of the window the mic hands out', () => {
    expect(WAVE_BARS * 0.02).toBeCloseTo(LIVE_WINDOW_S)
  })
  it('live waveform without a recorder renders empty', () => {
    const mic = { snapshot: vi.fn(() => null) }
    render(<LiveWave mic={mic} color="#F5CB00" />)
    act(() => { vi.advanceTimersByTime(WAVE_MS * 3) })
    expect(mic.snapshot).toHaveBeenCalled()
    expect(screen.getByTestId('live-wave')).toBeInTheDocument()
    expect(screen.queryAllByTestId('wave-bar')).toHaveLength(0)
  })
  it('draws louder bars for louder input', () => {
    let s = frames(0.02)
    render(<LiveWave mic={{ snapshot: () => s }} color="#F5CB00" />)
    act(() => { vi.advanceTimersByTime(WAVE_MS) })
    const quiet = heights()
    expect(quiet).toHaveLength(WAVE_BARS)
    s = frames(0.15)
    act(() => { vi.advanceTimersByTime(WAVE_MS) })
    const loud = heights()
    expect(loud).toHaveLength(WAVE_BARS)
    loud.forEach((h, i) => expect(h).toBeGreaterThan(quiet[i]))
  })
  it('stays flat when quiet, and the newest sound is on the right', () => {
    const s = new Float32Array(WAVE_BARS * 10)
    s.fill(0.2, s.length - 10)                       // only the last 20 ms frame is loud
    render(<LiveWave mic={{ snapshot: () => s }} color="#F5CB00" />)
    act(() => { vi.advanceTimersByTime(WAVE_MS) })
    const h = heights()
    expect(new Set(h.slice(0, -1)).size).toBe(1)     // silence: every bar at the same flat height
    expect(h[h.length - 1]).toBeGreaterThan(h[0])
  })
  it('bars are rounded and take the given colour', () => {
    render(<LiveWave mic={{ snapshot: () => frames(0.1) }} color="#F5CB00" />)
    act(() => { vi.advanceTimersByTime(WAVE_MS) })
    const bar = screen.getAllByTestId('wave-bar')[0]
    expect(bar).toHaveClass('rounded-full')
    expect(bar.style.backgroundColor).toBe('rgb(245, 203, 0)')
  })
  it('polls the mic itself, so the page around it does not re-render with every frame', () => {
    let s: Float32Array | null = null
    const renders = vi.fn()
    const mic = { snapshot: () => s }
    function Parent() { renders(); return <LiveWave mic={mic} color="#F5CB00" /> }
    render(<Parent />)
    s = frames(0.1)
    act(() => { vi.advanceTimersByTime(WAVE_MS) })
    expect(screen.getAllByTestId('wave-bar')).toHaveLength(WAVE_BARS)
    s = null
    act(() => { vi.advanceTimersByTime(WAVE_MS) })
    expect(screen.queryAllByTestId('wave-bar')).toHaveLength(0)
    expect(renders).toHaveBeenCalledTimes(1)
  })
})
