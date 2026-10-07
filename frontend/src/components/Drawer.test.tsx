import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
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
      onJump={noop} onToggle={noop} onEdit={noop} onSplit={noop} onMerge={noop} />)
    expect(screen.getAllByTestId('passage-header').map((h) => h.textContent)).toEqual(['P1✓', 'P2'])
    expect(within(screen.getByTestId('passage-0')).getAllByRole('button', { name: /^Actions for sentence/ })).toHaveLength(2)
  })
})
