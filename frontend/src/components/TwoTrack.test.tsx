import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { Segment } from '../api/types'
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
})
