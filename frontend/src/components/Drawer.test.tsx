import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Passage, Segment } from '../api/types'
import Drawer from './Drawer'

const seg = (id: number, attempts = 0): Segment => ({
  id, lesson_id: 1, idx: id - 10, start_s: 0, end_s: 1, text: `句子${id}`, translation: null, words_json: null, ref_alignment_json: null,
  difficulty_flag: false, anki_note_id: null, last_score: null, best_score: null, attempts,
})
const passages: Passage[] = [
  { idx: 0, title: 'P1', start_s: 0, end_s: 1, segment_ids: [10, 11], done: false },
  { idx: 1, title: 'P2', start_s: 1, end_s: 2, segment_ids: [12], done: false },
]
const noop = () => {}

describe('<Drawer> passages', () => {
  it('groups sentences under passage headers with a ✓ once the passage is done', () => {
    render(<Drawer segments={[seg(10, 1), seg(11), seg(12)]} idx={0} open pendingIds={new Set()} passages={passages} practised={[11]}
      onJump={noop} onClose={noop} onEdit={noop} onSplit={noop} onMerge={noop} />)
    expect(screen.getAllByTestId('passage-header').map((h) => h.textContent)).toEqual(['P1✓', 'P2'])
    expect(within(screen.getByTestId('passage-0')).getAllByRole('button', { name: /^Actions for sentence/ })).toHaveLength(2)
  })
})

describe('<Drawer> close button', () => {
  it('is a labelled ghost button with L as the hint, not a "◂ L" key face', () => {
    const onClose = vi.fn()
    render(<Drawer segments={[seg(10)]} idx={0} open pendingIds={new Set()} onJump={noop} onClose={onClose} onEdit={noop} onSplit={noop} onMerge={noop} />)
    const btn = screen.getByRole('button', { name: 'Close lesson list (L)' })
    expect(btn).toHaveTextContent('Lesson list')
    expect(within(btn).getByText('L')).toHaveClass('text-fgdim')
    expect(btn.textContent).not.toContain('◂')
    fireEvent.click(btn)
    expect(onClose).toHaveBeenCalledTimes(1)
  })
})

describe('<Drawer> opening', () => {
  it('scrolls the current sentence into view, centred', () => {
    const scroll = vi.fn()
    const orig = Element.prototype.scrollIntoView
    Element.prototype.scrollIntoView = scroll
    try {
      render(<Drawer segments={[seg(10), seg(11), seg(12)]} idx={1} open pendingIds={new Set()} onJump={noop} onClose={noop} onEdit={noop} onSplit={noop} onMerge={noop} />)
      expect(scroll).toHaveBeenCalledTimes(1)
      expect(scroll).toHaveBeenCalledWith({ block: 'center' })
      expect(scroll.mock.contexts[0]).toBe(screen.getByText('句子11').closest('div')!.parentElement)
    } finally { Element.prototype.scrollIntoView = orig }
  })
})
