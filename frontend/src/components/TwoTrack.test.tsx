import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Score, ScoredSyllable, Segment } from '../api/types'
import TwoTrack from './TwoTrack'

// What each track hands its Waveform and PitchLine, in render order (reference first, then you), last render wins.
const h = vi.hoisted(() => ({ waves: [] as Record<string, unknown>[], lines: [] as Record<string, unknown>[] }))
vi.mock('./Waveform', () => ({ default: (p: Record<string, unknown>) => { h.waves.push(p); return <canvas data-testid="wave" /> } }))
vi.mock('./PitchLine', () => ({ default: (p: Record<string, unknown>) => { h.lines.push(p); return <svg data-testid="pitch-line" /> } }))

const segment: Segment = {
  id: 1, lesson_id: 1, idx: 0, start_s: 0, end_s: 2, text: '你好吗', translation: null, ref_alignment_json: null,
  words_json: [{ word: '你好吗', pinyin: 'nǐ hǎo ma', tones: [3, 3, 0], char_from: 0, char_to: 3, syllables: [
    { ch: '你', pinyin: 'nǐ', pinyin_toneless: 'ni', tone: 3 }, { ch: '好', pinyin: 'hǎo', pinyin_toneless: 'hao', tone: 3 },
    { ch: '吗', pinyin: 'ma', pinyin_toneless: 'ma', tone: 0 }] }],
  difficulty_flag: false, anki_note_id: null, last_score: null, best_score: null, attempts: 0,
}

describe('<TwoTrack>', () => {
  const origRO = globalThis.ResizeObserver, origCtx = HTMLCanvasElement.prototype.getContext
  beforeEach(() => {
    globalThis.ResizeObserver = class { observe() {} disconnect() {} } as unknown as typeof ResizeObserver
    HTMLCanvasElement.prototype.getContext = (() => null) as typeof origCtx // jsdom has no canvas
  })
  afterEach(() => { cleanup(); globalThis.ResizeObserver = origRO; HTMLCanvasElement.prototype.getContext = origCtx })

  it('one row of cells, the You row, with the highlighted syllables outlined; no reference cell row', () => {
    const noop = () => {}
    render(<TwoTrack segment={segment} refPeaks={null} refDuration={2} refPlayhead={null} youPeaks={null} youDuration={0} youPlayhead={null}
      onPlayRef={noop} onPlayYou={noop} highlight={[0, 2]} />)
    const cells = screen.getAllByRole('button').filter((b) => b.title !== '' && within(b).queryByText(/[你好吗]/))
    expect(cells).toHaveLength(3)
    expect(screen.queryByText(/nǐ 3/)).toBeNull()             // the reference row's "pinyin tone" labels are gone
    expect(cells.map((c) => c.classList.contains('ring-accent'))).toEqual([true, false, true])
  })

  const syl = (ch: string, pinyin: string, tone: number, sound?: ScoredSyllable['sound']): ScoredSyllable =>
    ({ ch, pinyin, tone, target_tone: tone, heard_tone: tone, status: 'ok', tone_score: 0.9, p_target: 0.9, contour: 0.9, ...(sound === undefined ? {} : { sound }) })
  const score = (sounds: (ScoredSyllable['sound'] | undefined)[]): Score => ({ overall: 0.8, tone_overall: 0.8, segmental_overall: null, rate_ratio: 1, ref_contour: null, usr_contour: null, warnings: [],
    syllables: [syl('你', 'nǐ', 3, sounds[0]), syl('好', 'hǎo', 3, sounds[1]), syl('吗', 'ma', 0, sounds[2])] })
  const slip = { status: 'slip' as const, heard: 'n', heard_pinyin: 'lǐ', z: 3, rule: 'fused' as const }
  const props = { segment, refPeaks: null, refDuration: 2, refPlayhead: null, youPeaks: null, youDuration: 0, youPlayhead: null, onPlayRef: () => {}, onPlayYou: () => {} }
  const cellButtons = () => screen.getAllByRole('button').filter((b) => b.title !== '' && within(b).queryByText(/[你好吗]/))

  it('a heard sound shows in the HEARD row under its cell, the expected pinyin in its tooltip; no purple ring', () => {
    render(<TwoTrack {...props} score={score([slip, undefined, undefined])} />)
    expect(screen.getByText('HEARD')).toBeInTheDocument()
    expect(screen.getByText('lǐ').closest('[data-slot]')).toHaveAttribute('title', 'heard lǐ instead of nǐ')
    expect(cellButtons().some((c) => c.classList.contains('ring-sound'))).toBe(false)
  })
  it('renders as before without sound fields', () => {
    render(<TwoTrack {...props} score={score([undefined, undefined, undefined])} />)
    expect(screen.queryByText('HEARD')).toBeNull()
    expect(cellButtons().some((c) => c.classList.contains('ring-sound'))).toBe(false)
    expect(cellButtons().map((c) => c.textContent)).toEqual(['你390', '好390', '吗090'])
  })
  it('each track plays from a labelled button with its key as the hint, not "▶ Space" / "▶ R" key faces', () => {
    const calls: string[] = []
    const { rerender } = render(<TwoTrack {...props} onPlayRef={() => calls.push('ref')} onPlayYou={() => calls.push('you')} />)
    expect(screen.queryByText(/▶/)).toBeNull()
    const listen = screen.getByRole('button', { name: 'Listen (Space)' }), me = screen.getByRole('button', { name: 'Me (R)' })
    expect(within(listen).getByText('Space')).toHaveClass('text-fgdim')
    expect(within(me).getByText('R')).toHaveClass('text-fgdim')
    expect(me).toBeDisabled()                                  // no take yet
    fireEvent.click(listen)
    rerender(<TwoTrack {...props} youDuration={1.5} onPlayRef={() => calls.push('ref')} onPlayYou={() => calls.push('you')} />)
    fireEvent.click(screen.getByRole('button', { name: 'Me (R)' }))
    expect(calls).toEqual(['ref', 'you'])
  })
  it('clicking a You cell calls onPlayYouSyllable(i)', () => {
    const calls: number[] = []
    render(<TwoTrack {...props} score={score([undefined, undefined, undefined])} onPlayYouSyllable={(i) => calls.push(i)} />)
    fireEvent.click(cellButtons()[1])
    expect(calls).toEqual([1])
  })

  describe('speech-aligned tracks on one time scale', () => {
    // Reference clip 10 … 12 s, voice 10.5 … 11.6 (1.1 s) -> window 0.4 … 1.7 of the clip. A 4.9 s take, voice 1.8 … 3.1
    // (1.3 s) -> window 1.7 … 3.2. Peaks at 10 ms a bucket, so the windows fall on bucket edges.
    const aligned: Segment = { ...segment, start_s: 10, end_s: 12, ref_alignment_json: [
      { ch: '你', start: 10.5, end: 10.8, conf: 1 }, { ch: '好', start: 10.8, end: 11.1, conf: 1 }, { ch: '吗', start: 11.1, end: 11.6, conf: 1 }] }
    const refPeaks = Float32Array.from({ length: 200 }, (_, i) => i), youPeaks = Float32Array.from({ length: 490 }, (_, i) => i)
    const usr = { t0_s: 1.75, step_ms: 10, f0_st: [1, 2, 3], spans: [[1.8, 2.2], [2.2, 2.7], [2.7, 3.1]] as [number, number][] }
    const ref = { t0_s: 0.45, step_ms: 10, f0_st: Array.from({ length: 120 }, () => 1), spans: [[0.5, 0.8], [0.8, 1.1], [1.1, 1.6]] as [number, number][] }
    const scored = (rate: number | null): Score => ({ ...score([undefined, undefined, undefined]), rate_ratio: rate, ref_contour: ref, usr_contour: usr })
    const track = { ...props, segment: aligned, refPeaks, refDuration: 2, youPeaks, youDuration: 4.9 }
    const lastTwo = <T,>(xs: T[]) => xs.slice(-2)
    beforeEach(() => { h.waves.length = 0; h.lines.length = 0 })

    it('slices each waveform to its window and draws both at the scale that makes the longer one fill the box', () => {
      render(<TwoTrack {...track} score={scored(1.25)} />)
      const [r, y] = lastTwo(h.waves)
      expect((r.peaks as Float32Array)[0]).toBe(40); expect((r.peaks as Float32Array).length).toBe(130) // 0.4 … 1.7 s
      expect((y.peaks as Float32Array)[0]).toBe(170); expect((y.peaks as Float32Array).length).toBe(150) // 1.7 … 3.2 s
      expect(r.duration).toBeCloseTo(1.3, 6); expect(y.duration).toBeCloseTo(1.5, 6)
      expect(r.pxPerSec).toBe(y.pxPerSec)
      expect((y.duration as number) * (y.pxPerSec as number)).toBeCloseTo(600 - 16, 6)              // the longer fills the width
      // ticks at the syllable ends, from the window start
      expect((r.ticks as number[]).map((t) => +t.toFixed(6))).toEqual([0.4, 0.7, 1.2])
    })
    it('shifts playheads and pitch by the window start; the ghost stays on your syllables', () => {
      render(<TwoTrack {...track} score={scored(1.25)} refPlayhead={1.0} youPlayhead={2.0} />)
      const [r, y] = lastTwo(h.waves)
      expect(r.playhead).toBeCloseTo(0.6, 6); expect(y.playhead).toBeCloseTo(0.3, 6)
      const [rl, yl] = lastTwo(h.lines) as { series: { points: [number, number | null][] }[]; duration: number }[]
      expect(rl.series[0].points[0][0]).toBeCloseTo(0.05, 6)          // ref frame 0.45 s - 0.4
      expect(yl.series[1].points[0][0]).toBeCloseTo(0.05, 6)          // your frame 1.75 s - 1.7
      expect(yl.series[0].points[0][0]).toBeCloseTo(0.1, 6)           // ghost starts on your first syllable, 1.8 s - 1.7
      expect(rl.duration).toBeCloseTo(1.3, 6); expect(yl.duration).toBeCloseTo(1.5, 6)
    })
    it('the speed is the score’s rate_ratio; voice lengths in the captions', () => {
      render(<TwoTrack {...track} score={scored(1.25)} />)
      expect(screen.getByText(/Reference · 1\.1 s/)).toBeInTheDocument()
      expect(screen.getByText('You · 1.3 s · 1.25×')).toBeInTheDocument()
    })
    it('before scoring the take is trimmed by its peaks and the speed is the voice-length ratio', () => {
      const loud = Float32Array.from({ length: 490 }, (_, i) => (i >= 150 && i < 280 ? 0.5 : 0.001)) // voice 1.5 … 2.8 s
      render(<TwoTrack {...track} youPeaks={loud} score={null} />)
      const y = h.waves.at(-1)!
      expect((y.peaks as Float32Array).length).toBe(150)               // 1.4 … 2.9 s
      expect(screen.getByText('You · 1.3 s · 1.18×')).toBeInTheDocument()
    })
  })
})
