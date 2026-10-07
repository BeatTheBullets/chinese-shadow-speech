import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import type { Segment } from '../api/types'
import FlowView from './FlowView'

const seg = (id: number, idx: number, text: string, start: number): Segment => ({
  id, lesson_id: 1, idx, start_s: start, end_s: start + 2, text, translation: null, words_json: null,
  ref_alignment_json: [{ ch: text[0], start: start + 0.1, end: start + 1.0, conf: 1 }, { ch: text[1], start: start + 1.0, end: start + 1.9, conf: 1 }],
  difficulty_flag: false, anki_note_id: null, last_score: null, best_score: null, attempts: 0,
})
const base = {
  segments: [seg(1, 0, '你好', 0), seg(2, 1, '再见', 2), seg(3, 2, '谢谢', 4)], current: 0, first: 0, last: 2, pending: new Set<number>(), rate: 1, now: 100,
  level: 0.1, cue: { icon: '🎧', text: 'Listen', tone: 'ref' as const }, clipTime: null, turn: null,
}
const original = Range.prototype.getClientRects

describe('<FlowView>', () => {
  afterEach(() => { cleanup(); Range.prototype.getClientRects = original })

  it('shows the cue with the mic meter, the current line large and the next line dimmed below it', () => {
    render(<FlowView {...base} sub="along" showText />)
    expect(screen.getByTestId('cue-line')).toHaveTextContent('Listen')
    expect(screen.getByRole('meter', { name: 'Microphone level' })).toBeInTheDocument()
    expect(screen.getByText('你好', { selector: 'p.sentence' })).toBeInTheDocument()
    expect(screen.getByTestId('next-line')).toHaveTextContent('再见')
    expect(screen.getByTestId('next-line').className).toContain('text-fgdim')
  })
  it('after, during the turn: the turn bar shrinks and the ghost line fills at the reference pace', () => {
    render(<FlowView {...base} sub="after" showText={false} now={101} turn={{ startedAt: 99, duration: 4 }} />)
    expect((screen.getByTestId('turn-bar').firstChild as HTMLElement).style.width).toBe('50%')
    const cells = screen.getByTestId('ghost-line').querySelectorAll('span > span')
    expect([...cells].map((c) => (c as HTMLElement).style.width)).toEqual(['100%', '100%'])
  })
  it('after: count-in dots over the last 1.5 s of the clip', () => {
    render(<FlowView {...base} sub="after" showText clipTime={1.0} />)
    expect(screen.getByLabelText('starting in 2')).toBeInTheDocument()
    expect(screen.queryByTestId('turn-bar')).toBeNull()
  })
  it('the colour wipe follows the clip-relative media time, on a layer outside the sentence', () => {
    Range.prototype.getClientRects = function (this: Range) {
      return [{ left: this.startOffset * 40, top: 0, width: 40, height: 40 }] as unknown as DOMRectList
    }
    const { container } = render(<FlowView {...base} segments={[seg(1, 0, '你好', 10), seg(2, 1, '再见', 12)]} sub="along" showText clipTime={0.55} />)
    const layer = screen.getByTestId('wipe')
    expect(container.querySelector('p.sentence')!.contains(layer)).toBe(false)
    const widths = [...layer.children].map((b) => parseFloat((b as HTMLElement).style.width))
    expect(widths).toHaveLength(1)
    expect(widths[0]).toBeCloseTo(20) // 你 half-way through its 0.1 → 1.0 s of the clip
  })
  it('along: count-in before the next line only when the silence before it is at least 0.5 s', () => {
    const late = { ...seg(2, 1, '再见', 2), ref_alignment_json: [{ ch: '再', start: 2.6, end: 3.0, conf: 1 }, { ch: '见', start: 3.0, end: 3.5, conf: 1 }] }
    const { rerender } = render(<FlowView {...base} segments={[seg(1, 0, '你好', 0), late]} sub="along" showText clipTime={1.5} />)
    expect(screen.getByLabelText('starting in 3')).toBeInTheDocument() // 0.7 s of silence: count in to 2.6 s
    rerender(<FlowView {...base} sub="along" showText clipTime={1.5} />)          // 0.2 s of silence: none
    expect(screen.queryByLabelText(/starting in/)).toBeNull()
  })
  it('along: the count-in runs on through the lead silence of the next clip, down to its first syllable', () => {
    const late = { ...seg(2, 1, '再见', 2), ref_alignment_json: [{ ch: '再', start: 2.6, end: 3.0, conf: 1 }, { ch: '见', start: 3.0, end: 3.5, conf: 1 }] }
    const segments = [seg(1, 0, '你好', 0), late, seg(3, 2, '谢谢', 4)]
    const { rerender } = render(<FlowView {...base} segments={segments} sub="along" showText clipTime={2.0} />)
    expect(screen.getByLabelText('starting in 2')).toBeInTheDocument() // end of 你好: 0.6 s to go
    rerender(<FlowView {...base} segments={segments} current={1} sub="along" showText clipTime={0} />)
    expect(screen.getByLabelText('starting in 2')).toBeInTheDocument() // start of 再见: still 0.6 s to go
    rerender(<FlowView {...base} segments={segments} current={1} sub="along" showText clipTime={0.3} />)
    expect(screen.getByLabelText('starting in 1')).toBeInTheDocument()
    rerender(<FlowView {...base} segments={segments} current={1} first={1} sub="along" showText clipTime={0} />)
    expect(screen.queryByLabelText(/starting in/)).toBeNull() // the first line of the run carries nothing over
  })
  it('the last sentence of the run previews nothing: no next line, no count-in for it', () => {
    const late = { ...seg(2, 1, '再见', 2), ref_alignment_json: [{ ch: '再', start: 2.6, end: 3.0, conf: 1 }, { ch: '见', start: 3.0, end: 3.5, conf: 1 }] }
    render(<FlowView {...base} segments={[seg(1, 0, '你好', 0), late]} last={0} sub="along" showText clipTime={1.5} />)
    expect(screen.queryByTestId('next-line')).toBeNull()
    expect(screen.queryByLabelText(/starting in/)).toBeNull()
  })
})
