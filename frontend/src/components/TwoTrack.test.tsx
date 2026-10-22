import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { Score, ScoredSyllable, Segment } from '../api/types'
import TwoTrack from './TwoTrack'

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

  it('outlines the highlighted syllables in both rows', () => {
    const noop = () => {}
    render(<TwoTrack segment={segment} refPeaks={null} refDuration={2} refPlayhead={null} youPeaks={null} youDuration={0} youPlayhead={null}
      onPlayRef={noop} onPlayYou={noop} onPlaySyllable={noop} highlight={[0, 2]} />)
    const cells = screen.getAllByRole('button').filter((b) => b.title !== '' && within(b).queryByText(/[你好吗]/))
    expect(cells).toHaveLength(6)
    expect(cells.map((c) => c.classList.contains('ring-accent'))).toEqual([true, false, true, true, false, true])
  })

  const syl = (ch: string, pinyin: string, tone: number, sound?: ScoredSyllable['sound']): ScoredSyllable =>
    ({ ch, pinyin, tone, target_tone: tone, heard_tone: tone, status: 'ok', tone_score: 0.9, p_target: 0.9, contour: 0.9, ...(sound === undefined ? {} : { sound }) })
  const score = (sounds: (ScoredSyllable['sound'] | undefined)[]): Score => ({ overall: 0.8, tone_overall: 0.8, segmental_overall: null, rate_ratio: 1, ref_contour: null, usr_contour: null, warnings: [],
    syllables: [syl('你', 'nǐ', 3, sounds[0]), syl('好', 'hǎo', 3, sounds[1]), syl('吗', 'ma', 0, sounds[2])] })
  const slip = { status: 'slip' as const, heard: 'n', heard_pinyin: 'lǐ', z: 3, rule: 'fused' as const }
  const props = { segment, refPeaks: null, refDuration: 2, refPlayhead: null, youPeaks: null, youDuration: 0, youPlayhead: null, onPlayRef: () => {}, onPlayYou: () => {}, onPlaySyllable: () => {} }
  const cellButtons = () => screen.getAllByRole('button').filter((b) => b.title !== '' && within(b).queryByText(/[你好吗]/))

  it('rings the reference cells above heard sounds', () => {
    render(<TwoTrack {...props} score={score([slip, undefined, undefined])} />)
    expect(screen.getByText('HEARD')).toBeInTheDocument()
    expect(screen.getByText('lǐ')).toBeInTheDocument()
    expect(cellButtons().map((c) => c.classList.contains('ring-sound'))).toEqual([true, false, false, false, false, false])
  })
  it('renders as before without sound fields', () => {
    render(<TwoTrack {...props} score={score([undefined, undefined, undefined])} />)
    expect(screen.queryByText('HEARD')).toBeNull()
    expect(cellButtons().some((c) => c.classList.contains('ring-sound'))).toBe(false)
    expect(cellButtons().map((c) => c.textContent)).toEqual(['你nǐ 3', '好hǎo 3', '吗ma 0', '你390', '好390', '吗090'])
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
    fireEvent.click(cellButtons()[4])
    expect(calls).toEqual([1])
  })
})
