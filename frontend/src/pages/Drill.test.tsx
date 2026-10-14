import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DrillFocus, DrillRecent, DrillSession } from '../api/types'
import { ApiError } from '../api/client'
import Shell from '../components/Shell'

const h = vi.hoisted(() => ({ drill: { focuses: vi.fn(), recent: vi.fn(), start: vi.fn(), end: vi.fn(), summary: vi.fn() } }))
vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api/client')>()), api: { drill: h.drill } }))
import Drill from './Drill'

const focus = (kind: DrillFocus['kind'], key: string, label: string, mean: number, n: number): DrillFocus => ({ kind, key, label, mean, n })
const focuses = [
  focus('pair', '3-3', 'tone pair 3→3', 0.31, 24), focus('tone', '3', 'tone 3 (low)', 0.42, 120),
  focus('char', '在', '在 zài', 0.5, 12), focus('tone', '2', 'tone 2 (rising)', 0.6, 80),
]
const session = (kind: string, key: string, label: string): DrillSession => ({ id: 7, kind, key, label, short: false, items: [] })
const last: DrillRecent = { id: 5, kind: 'tone', key: '4', label: 'tone 4 (falling)', started_at: '', ended_at: '2026-10-13T10:00:00', first_mean: 0.52, best_mean: 0.71 }
const future = { v7_startTransition: true, v7_relativeSplatPath: true }
const renderAt = (url = '/drill') => render(<MemoryRouter future={future} initialEntries={[url]}><Drill /></MemoryRouter>)

describe('<Drill> start screen', () => {
  beforeEach(() => {
    Object.values(h.drill).forEach((f) => f.mockReset())
    // Rotation: the weakest focus (3→3) was drilled last time, so `auto` is the next one.
    h.drill.focuses.mockResolvedValue({ focuses, auto: { kind: 'tone', key: '3' } })
    h.drill.recent.mockResolvedValue([last])
  })
  afterEach(cleanup)

  it("shows today's focus with its mean, two alternatives and the last drill", async () => {
    renderAt()
    expect(await screen.findByText("Today's focus")).toBeInTheDocument()
    expect(screen.getByText('tone 3 (low)')).toBeInTheDocument()
    expect(screen.getByText('your mean 42 · 120 syllables')).toBeInTheDocument()
    expect(screen.getByText('tone pair 3→3')).toBeInTheDocument()
    expect(screen.getByText('在 zài')).toBeInTheDocument()
    expect(screen.queryByText('tone 2 (rising)')).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Start' })).toHaveLength(3)
    expect(screen.getByText('Last drill: tone 4 (falling) · 52 → 71')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'See summary' })).toBeInTheDocument()
    expect(h.drill.recent).toHaveBeenCalledWith(1)
  })

  it('Start starts that focus and hands the session to the runner', async () => {
    h.drill.start.mockResolvedValue({ ...session('char', '在', '在 zài'), items: [{}, {}] as DrillSession['items'] })
    renderAt()
    await screen.findByText("Today's focus")
    fireEvent.click(screen.getAllByRole('button', { name: 'Start' })[2])
    expect(h.drill.start).toHaveBeenCalledWith({ kind: 'char', key: '在' })
    expect(await screen.findByText('在 zài · 2 sentences')).toBeInTheDocument()
    expect(screen.queryByText("Today's focus")).not.toBeInTheDocument()
  })

  it('?kind=&key= starts that focus immediately, skipping the start screen', async () => {
    h.drill.start.mockResolvedValue(session('pair', '3-3', 'tone pair 3→3'))
    renderAt('/drill?kind=pair&key=3-3')
    expect(await screen.findByText('tone pair 3→3 · 0 sentences')).toBeInTheDocument()
    expect(h.drill.start).toHaveBeenCalledTimes(1)
    expect(h.drill.start).toHaveBeenCalledWith({ kind: 'pair', key: '3-3' })
    expect(screen.queryByText("Today's focus")).not.toBeInTheDocument()
  })

  it('without a qualifying focus explains why and links to the Library', async () => {
    h.drill.focuses.mockResolvedValue({ focuses: [], auto: null })
    h.drill.recent.mockResolvedValue([])
    renderAt()
    expect(await screen.findByText("Practise a few sentences first — drills start once there's enough to know your weak spots.")).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open the Library' })).toHaveAttribute('href', '/library')
    expect(screen.queryByRole('button', { name: 'Start' })).not.toBeInTheDocument()
  })

  it('a focus with no sentences shows a readable message', async () => {
    h.drill.start.mockRejectedValue(new ApiError(404, 'Not Found', '{"detail":"no sentences contain this focus"}', 'no sentences contain this focus'))
    renderAt()
    await screen.findByText("Today's focus")
    fireEvent.click(screen.getAllByRole('button', { name: 'Start' })[0])
    expect(await screen.findByText('No sentences contain this focus yet.')).toBeInTheDocument()
    expect(screen.getByText("Today's focus")).toBeInTheDocument()
  })
})

describe('<Shell>', () => {
  afterEach(cleanup)
  it('has a Drill tab after Review linking to /drill', () => {
    render(<MemoryRouter future={future}><Shell><div /></Shell></MemoryRouter>)
    const tabs = screen.getAllByRole('link').map((a) => a.textContent)
    expect(tabs.indexOf('Drill')).toBe(tabs.indexOf('Review') + 1)
    expect(screen.getByRole('link', { name: 'Drill' })).toHaveAttribute('href', '/drill')
  })
})
