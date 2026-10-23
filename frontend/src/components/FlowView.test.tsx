import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { FlowRun, Segment } from '../api/types'
import FlowView, { FlowSetup, FlowTransport, WINDOW } from './FlowView'

const seg = (id: number, idx: number, text: string, start: number): Segment => ({
  id, lesson_id: 1, idx, start_s: start, end_s: start + 2, text, translation: null, words_json: null,
  ref_alignment_json: [{ ch: text[0], start: start + 0.1, end: start + 1.0, conf: 1 }, { ch: text[1], start: start + 1.0, end: start + 1.9, conf: 1 }],
  difficulty_flag: false, anki_note_id: null, last_score: null, best_score: null, attempts: 0,
})
const base = {
  segments: [seg(1, 0, '你好', 0), seg(2, 1, '再见', 2), seg(3, 2, '谢谢', 4)], current: 0, first: 0, last: 2, pending: new Set<number>(), rate: 1, now: 100,
  mic: { snapshot: () => null }, stage: 'listen' as const, startedAt: performance.now() / 1000, clipTime: null, turn: null, running: true,
}
const original = Range.prototype.getClientRects

describe('<FlowView>', () => {
  afterEach(() => { cleanup(); Range.prototype.getClientRects = original })

  it('along: the speak-along stage with the live waveform, the current line large and the next line dimmed below it', () => {
    render(<FlowView {...base} stage="along" startedAt={performance.now() / 1000 - 3} sub="along" showText />)
    expect(screen.getByTestId('stage')).toHaveTextContent('Speak along')
    expect(screen.getByTestId('stage')).toHaveClass('border-record')
    expect(screen.getByTestId('rec-timer')).toHaveTextContent('0:03')
    expect(screen.getByTestId('live-wave')).toBeInTheDocument()
    expect(screen.queryByRole('meter')).toBeNull()
    expect(screen.getByText('你好', { selector: 'p.sentence' })).toBeInTheDocument()
    expect(screen.getByTestId('next-line')).toHaveTextContent('再见')
    expect(screen.getByTestId('next-line').className).toContain('text-fgdim')
    expect(screen.queryByText(/stops by itself/)).toBeNull()                      // Flow's turns end on their own clock
  })
  it('after, during the turn: the turn bar shrinks and the ghost line fills at the reference pace', () => {
    render(<FlowView {...base} stage="yourTurn" sub="after" showText={false} now={101} turn={{ startedAt: 99, duration: 4 }} />)
    expect(screen.getByTestId('stage')).toHaveTextContent('Your turn')
    expect(screen.getByTestId('live-wave')).toBeInTheDocument()
    expect((screen.getByTestId('turn-bar').firstChild as HTMLElement).style.width).toBe('50%')
    const cells = screen.getByTestId('ghost-line').querySelectorAll('span > span')
    expect([...cells].map((c) => (c as HTMLElement).style.width)).toEqual(['100%', '100%'])
  })
  it('Flow after shows 3·2·1 over the end of the clip', () => {
    const { rerender } = render(<FlowView {...base} sub="after" showText clipTime={0.4} />)
    expect(screen.getByTestId('stage')).toHaveTextContent('Listening')            // before the last 1.5 s: listening
    expect(screen.queryByText('Get ready')).toBeNull()
    const at = (t: number) => { rerender(<FlowView {...base} sub="after" showText clipTime={t} />); return screen.getByTestId('countdown').textContent }
    expect([at(0.5), at(1.0), at(1.6)]).toEqual(['3', '2', '1'])
    expect(screen.getByLabelText('starting in 1')).toHaveClass('text-accent')
    expect(screen.getByText('Get ready')).toBeInTheDocument()
    expect(screen.getByTestId('stage')).not.toHaveClass('border-record')
    expect(screen.queryByTestId('live-wave')).toBeNull()                          // listening still: no waveform of you yet
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
  it('along with a countdown: the along frame, text, timer and live waveform stay, with 3·2·1 inside', () => {
    const late = { ...seg(2, 1, '再见', 2), ref_alignment_json: [{ ch: '再', start: 2.6, end: 3.0, conf: 1 }, { ch: '见', start: 3.0, end: 3.5, conf: 1 }] }
    render(<FlowView {...base} segments={[seg(1, 0, '你好', 0), late]} stage="along" startedAt={performance.now() / 1000 - 4} sub="along" showText clipTime={1.5} />)
    const stage = screen.getByTestId('stage')
    expect(stage).toHaveAttribute('data-stage', 'along')
    expect(stage).toHaveClass('border-record')
    expect(stage).toHaveTextContent('Speak along')
    expect(screen.getByTestId('rec-dot')).toBeInTheDocument()
    expect(screen.getByTestId('rec-timer')).toHaveTextContent('0:04')
    expect(screen.getByTestId('live-wave')).toBeInTheDocument()
    expect(screen.getByTestId('countdown').textContent).toBe('3')
    expect(stage).toContainElement(screen.getByLabelText('starting in 3'))
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
  const ten = '一二三四五六七八九十'.split('').map((c, i) => seg(i + 1, i, `${c}${c}`, i * 2))
  const lines = () => screen.getAllByTestId('flow-line').map((l) => l.textContent)
  it(`shows only a window round the current line, ${WINDOW.before} before and ${WINDOW.after} after, centred above and below the stage`, () => {
    expect(WINDOW).toEqual({ before: 2, after: 3 })
    render(<FlowView {...base} segments={ten} current={5} last={9} sub="along" showText />)
    expect(lines()).toEqual(['4四四', '5五五', '7七七', '8八八', '9九九'])  // each line: its number, then its text
    expect(screen.getByTestId('stage')).toHaveTextContent('六六')
    expect(screen.queryByText('一一')).toBeNull()
    expect(screen.queryByText('十十')).toBeNull()
    expect(screen.getByTestId('flow-transcript')).toHaveClass('items-center')
    screen.getAllByTestId('flow-line').forEach((l) => expect(l).toHaveClass('justify-center'))
    const order = [...screen.getByTestId('flow-transcript').querySelectorAll('[data-testid="flow-line"], [data-testid="flow-current"]')].map((e) => e.getAttribute('data-testid'))
    expect(order).toEqual(['flow-line', 'flow-line', 'flow-current', 'flow-line', 'flow-line', 'flow-line'])
  })
  it('the window advances with the run, and keeps its slots at the ends so the stage never moves', () => {
    const { rerender } = render(<FlowView {...base} segments={ten} current={0} last={9} sub="along" showText />)
    expect(lines()).toEqual(['2二二', '3三三', '4四四'])
    expect(screen.getAllByTestId('flow-pad')).toHaveLength(2)                // two empty slots above the first line
    rerender(<FlowView {...base} segments={ten} current={1} last={9} sub="along" showText />)
    expect(lines()).toEqual(['1一一', '3三三', '4四四', '5五五'])
    expect(screen.getAllByTestId('flow-pad')).toHaveLength(1)
    rerender(<FlowView {...base} segments={ten} current={9} last={9} sub="along" showText />)
    expect(lines()).toEqual(['8八八', '9九九'])
    expect(screen.getAllByTestId('flow-pad')).toHaveLength(3)
  })
  it('the run\'s past lines are dimmed and finished ones keep their mark; the next one is marked', () => {
    render(<FlowView {...base} segments={ten} current={5} last={9} pending={new Set([5])} sub="along" showText />)
    const [l4, l5, l7] = screen.getAllByTestId('flow-line')
    expect(l4.querySelector('.font-hanzi')!.className).toContain('text-fgdim')
    expect(l5.querySelector('.rounded-full')!.className).not.toBe(l4.querySelector('.rounded-full')!.className) // 5 is pending
    expect(l7).toContainElement(screen.getByTestId('next-line'))
  })
  it('lines above the stage are cut to one line (the full text in their title); lines below wrap, to read ahead', () => {
    const long = [seg(1, 0, '你好', 0), seg(2, 1, '再见', 2), { ...seg(3, 2, '谢谢', 4), text: '谢'.repeat(80) }]
    render(<FlowView {...base} segments={long} current={1} sub="along" showText />)
    const [above, below] = screen.getAllByTestId('flow-line')
    const text = (l: HTMLElement) => l.querySelector('.font-hanzi') as HTMLElement
    expect(text(above)).toHaveClass('truncate')
    expect(text(above)).toHaveAttribute('title', '你好')
    expect(above).toHaveClass('h-8')
    expect(text(below)).not.toHaveClass('truncate')
    expect(below).not.toHaveClass('h-8')
    expect(below).toHaveClass('min-h-8')
    expect(text(below)).toHaveTextContent('谢'.repeat(80))
  })
  it('the stage is compact: its cue area only as tall as the ring', () => {
    render(<FlowView {...base} sub="after" showText />)
    expect(screen.getByTestId('stage-cue')).toHaveClass('min-h-20')
  })
  it('before a run: the start sentence on an idle stage, the settings shown above; once running nothing of them shows but their space stays', () => {
    const controls = <div data-testid="settings">from … to</div>
    const { rerender } = render(<FlowView {...base} running={false} controls={controls} stage="idle" sub="after" showText />)
    expect(screen.getByTestId('stage')).toHaveAttribute('data-stage', 'idle')
    expect(screen.getByTestId('stage')).toHaveTextContent('你好')
    expect(screen.getByTestId('settings')).toBeInTheDocument()
    const slot = screen.getByTestId('settings').parentElement!
    rerender(<FlowView {...base} running controls={controls} sub="after" showText />)
    expect(screen.queryByTestId('settings')).toBeNull()
    expect(slot).toHaveClass('min-h-9')
  })
  it('the last sentence of the run previews nothing: no next line, no count-in for it', () => {
    const late = { ...seg(2, 1, '再见', 2), ref_alignment_json: [{ ch: '再', start: 2.6, end: 3.0, conf: 1 }, { ch: '见', start: 3.0, end: 3.5, conf: 1 }] }
    render(<FlowView {...base} segments={[seg(1, 0, '你好', 0), late]} last={0} sub="along" showText clipTime={1.5} />)
    expect(screen.queryByTestId('next-line')).toBeNull()
    expect(screen.queryByLabelText(/starting in/)).toBeNull()
  })
})

describe('<FlowSetup>', () => {
  afterEach(cleanup)
  const at = (d: number, h: number, m: number) => new Date(2026, 9, d, h, m).toISOString()
  const run = (d: number, h: number, m: number, n: number): FlowRun => ({
    started_at: at(d, h, m), ended_at: at(d, h, m + 1), session_id: 1, items: Array.from({ length: n }, (_, k) => ({ segment_id: k + 1, idx: k, attempt_id: 100 + k, duration_s: 2 })),
  })
  const setup = (runs: FlowRun[], onReplay = vi.fn(), onChange = vi.fn(), sub: 'after' | 'along' = 'after') => {
    render(<FlowSetup segments={base.segments} from={0} to={1} sub={sub} onChange={onChange} runs={runs} onReplay={onReplay} />)
    return { onReplay, onChange }
  }
  const openPopup = () => fireEvent.click(screen.getByRole('button', { name: /^Sentences/ }))

  it('is one line: the After | Along switch, the Sentences button and, only with runs, Replay last run', () => {
    setup([])
    expect(screen.getByRole('button', { name: 'After' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Along' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: 'Sentences 1 – 2 ▾' })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.queryByRole('button', { name: /replay/i })).toBeNull()
    cleanup(); setup([run(7, 14, 5, 3)])
    expect(screen.getByRole('button', { name: 'Replay last run' })).toBeInTheDocument()
  })
  it('the switch toggles after / along', () => {
    const { onChange } = setup([], vi.fn(), vi.fn(), 'after')
    fireEvent.click(screen.getByRole('button', { name: 'Along' }))
    expect(onChange).toHaveBeenCalledWith({ sub: 'along' })
  })
  it('has no Start of its own (the bar\'s Start flow is the one start) and no ▶ (that is Listen\'s)', () => {
    setup([run(7, 14, 5, 3)])
    expect(screen.queryByRole('button', { name: /^Start/ })).toBeNull()
    expect(screen.getByTestId('flow-settings').textContent).not.toContain('▶')
  })
  it('the pop-up holds From, To and Past runs; it is closed at first, and Esc closes it while Space still reaches the page', () => {
    setup([run(7, 14, 5, 3), run(6, 9, 30, 2)])
    expect(screen.queryByRole('combobox', { name: 'Flow from' })).toBeNull()
    openPopup()
    expect(screen.getByRole('button', { name: /^Sentences/ })).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByRole('combobox', { name: 'Flow from' })).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Flow to' })).toBeInTheDocument()
    const past = screen.getByRole('combobox', { name: 'Past runs' })
    expect([...past.querySelectorAll('option')].map((o) => o.textContent)).toEqual(['Wed 14:05 · 3 sentences', 'Tue 09:30 · 2 sentences'])
    const onKey = vi.fn(); document.addEventListener('keydown', onKey)
    fireEvent.keyDown(document.body, { key: ' ' })
    expect(onKey).toHaveBeenCalledTimes(1)
    expect(screen.getByRole('combobox', { name: 'Flow from' })).toBeInTheDocument()
    fireEvent.keyDown(document.body, { key: 'Escape' })
    document.removeEventListener('keydown', onKey)
    expect(screen.queryByRole('combobox', { name: 'Flow from' })).toBeNull()
  })
  it('without runs the pop-up has no Past runs; From and To report their change', () => {
    const { onChange } = setup([])
    openPopup()
    expect(screen.queryByRole('combobox', { name: 'Past runs' })).toBeNull()
    fireEvent.change(screen.getByRole('combobox', { name: 'Flow to' }), { target: { value: '0' } })
    expect(onChange).toHaveBeenCalledWith({ to: 0 })
    fireEvent.change(screen.getByRole('combobox', { name: 'Flow from' }), { target: { value: '1' } })
    expect(onChange).toHaveBeenCalledWith({ from: 1 })
  })
  it('changing From or To blurs the select so Enter and Space go back to the page', () => {
    setup([])
    openPopup()
    for (const name of ['Flow from', 'Flow to']) {
      const sel = screen.getByRole('combobox', { name })
      sel.focus(); expect(document.activeElement).toBe(sel)
      fireEvent.change(sel, { target: { value: '0' } })
      expect(document.activeElement).not.toBe(sel)
    }
  })
  it('Replay last run plays the most recent run', () => {
    const runs = [run(7, 14, 5, 3), run(6, 9, 30, 2)]
    const { onReplay } = setup(runs)
    fireEvent.click(screen.getByRole('button', { name: 'Replay last run' }))
    expect(onReplay).toHaveBeenCalledWith(runs[0])
  })
  it('an older run picked in Past runs is the one replayed', () => {
    const runs = [run(7, 14, 5, 3), run(6, 9, 30, 2)]
    const { onReplay } = setup(runs)
    openPopup()
    fireEvent.change(screen.getByRole('combobox', { name: 'Past runs' }), { target: { value: '1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Replay earlier run' }))
    expect(onReplay).toHaveBeenCalledWith(runs[1])
  })
})

describe('<FlowTransport>', () => {
  afterEach(cleanup)
  const sound = { rate: 1, onRate: () => {}, volume: { reference: 1, guide: 0.5, onReference: () => {}, onGuide: () => {} } }

  it('uses the same groups as the bar: position, Stop on Enter, › skips; no previous, no Anki', () => {
    const onAction = vi.fn()
    render(<FlowTransport onAction={onAction} idx={1} total={3} sound={sound} hint="" error="" />)
    expect(screen.getByTestId('position')).toHaveTextContent('2 / 3')
    expect(screen.getByRole('button', { name: 'Previous sentence (←)' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Listen (Space)' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Me (R)' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: /Anki/ })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Stop (Enter)' }))
    fireEvent.click(screen.getByRole('button', { name: 'Next sentence (→)' }))
    expect(onAction.mock.calls).toEqual([['record'], ['next']])
    fireEvent.click(screen.getByRole('button', { name: 'Sound' }))
    expect(screen.getByLabelText('Guide level')).toBeInTheDocument()
  })
})
