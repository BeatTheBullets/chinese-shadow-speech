import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { DrillSummary as Summary } from '../api/types'
import DrillSummary from './DrillSummary'

const take = (attempt_id: number, mean: number, green: number) => ({ attempt_id, mean, green })
const summary: Summary = {
  id: 7, kind: 'tone', key: '3', label: 'tone 3 (low)', first_mean: 0.55, best_mean: 0.72, green_first: 3, green_best: 5, n_targets: 7,
  items: [
    { segment_id: 11, lesson_id: 3, lesson_title: 'Lesson A', idx: 0, text: '你好吗', targets: [0, 1], tries: 1, first: take(1, 0.9, 2), best: take(1, 0.9, 2), went_green: true },
    { segment_id: 12, lesson_id: 3, lesson_title: 'Lesson A', idx: 4, text: '我很好', targets: [0, 1, 2], tries: 3, first: take(2, 0.4, 1), best: take(4, 0.6, 2), went_green: false },
    { segment_id: 20, lesson_id: 5, lesson_title: 'Lesson B', idx: 2, text: '在家里', targets: [0, 2], tries: 0, first: null, best: null, went_green: false },
  ],
  history: [
    { session_id: 3, started_at: '2026-10-10T10:00:00', first_mean: 0.4, best_mean: 0.58 },
    { session_id: 7, started_at: '2026-10-14T10:00:00', first_mean: 0.55, best_mean: 0.72 },
  ],
}
const future = { v7_startTransition: true, v7_relativeSplatPath: true }
const renderSummary = (s = summary, onAgain = vi.fn(), onDone = vi.fn(), busy = false) =>
  render(<MemoryRouter future={future}><DrillSummary summary={s} onAgain={onAgain} onDone={onDone} busy={busy} /></MemoryRouter>)

describe('<DrillSummary>', () => {
  afterEach(cleanup)

  it('headlines first → best target means and green counts', () => {
    renderSummary()
    expect(screen.getByText('tone 3 (low): target syllables first try 55 → best 72 · green 3 → 5 of 7')).toBeInTheDocument()
  })

  it('lists the sentences that never went green, each with a Practice link', () => {
    renderSummary()
    const list = screen.getByRole('list', { name: 'Not green yet' })
    const rows = within(list).getAllByRole('listitem')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('我很好')
    expect(within(rows[0]).getByRole('link', { name: 'Open in Practice' })).toHaveAttribute('href', '/practice/3?idx=4')
    expect(within(rows[1]).getByRole('link', { name: 'Open in Practice' })).toHaveAttribute('href', '/practice/5?idx=2')
    expect(screen.queryByText('你好吗')).not.toBeInTheDocument()
  })

  it('"Drill these again" passes the never-green sentence ids; "Done" goes back', () => {
    const onAgain = vi.fn(), onDone = vi.fn()
    renderSummary(summary, onAgain, onDone)
    fireEvent.click(screen.getByRole('button', { name: 'Drill these again' }))
    expect(onAgain).toHaveBeenCalledWith([12, 20])
    fireEvent.click(screen.getByRole('button', { name: 'Done' }))
    expect(onDone).toHaveBeenCalled()
  })

  it('"Drill these again" is disabled while a run is starting', () => {
    const onAgain = vi.fn()
    renderSummary(summary, onAgain, vi.fn(), true)
    const again = screen.getByRole('button', { name: 'Drill these again' })
    expect(again).toBeDisabled()
    fireEvent.click(again)
    expect(onAgain).not.toHaveBeenCalled()
  })

  it('draws the focus history, first and best per session', () => {
    renderSummary()
    const chart = screen.getByRole('img', { name: 'Drill history for tone 3 (low)' })
    expect(chart.querySelectorAll('circle')).toHaveLength(4)
  })

  it('all green: no list and no drill-again', () => {
    renderSummary({ ...summary, items: summary.items.map((it) => ({ ...it, went_green: true })) })
    expect(screen.getByText('Every sentence went green.')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Drill these again' })).not.toBeInTheDocument()
  })
})
