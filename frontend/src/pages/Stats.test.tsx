import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

const h = vi.hoisted(() => ({ stats: {
  activity: vi.fn(() => Promise.resolve({ days: [] })), sentences: vi.fn(() => Promise.resolve({ sentences: [] })),
  tones: vi.fn(() => Promise.resolve({ tones: [{ tone: 3, mean: 0.55, n: 20 }], pairs: [{ prev_tone: 3, tone: 3, mean: 0.4, n: 6 }], weeks: [{ week: '2026-W41', tone: 3, mean: 0.55, n: 20 }] })),
  sounds: vi.fn(() => Promise.resolve({ sounds: [{ key: 'ch>c', label: 'ch said as c', slips: 2, chances: 10, rate: 0.2 }], weeks: [] })),
}, drill: { recent: vi.fn(() => Promise.resolve([] as unknown[])) } }))
vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api/client')>()), api: { stats: h.stats, drill: h.drill } }))
import Stats from './Stats'

describe('<Stats>', () => {
  it('shows tone means, the trend chart and the pair matrix', async () => {
    render(<MemoryRouter><Stats /></MemoryRouter>)
    expect(await screen.findByText(/Tone 3 \(low\)/)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /Tone scores per week/ })).toBeInTheDocument()
    expect(screen.getByTitle('after tone 3, tone 3: 40 (n 6)')).toBeInTheDocument()
  })

  const Where = () => { const l = useLocation(); return <p data-testid="where">{l.pathname + l.search}</p> }
  const renderRouted = () => render(<MemoryRouter><Routes><Route path="/" element={<Stats />} /><Route path="/drill" element={<Where />} /></Routes></MemoryRouter>)

  it.each([
    ['Drill tone 3', '/drill?kind=tone&key=3'],
    ['Drill tone pair 3→3', '/drill?kind=pair&key=3-3'],
    ['Drill ch said as c', '/drill?kind=sound&key=ch%3Ec'],
  ])('"%s" navigates to the drill page', async (name, url) => {
    renderRouted()
    await screen.findByText(/Tone 3 \(low\)/)
    fireEvent.click(await screen.findByRole('button', { name }))
    expect((await screen.findByTestId('where')).textContent).toBe(url)
  })

  it('lists recent drills with first → best, or says there are none', async () => {
    h.drill.recent.mockResolvedValueOnce([{ id: 1, kind: 'tone', key: '3', label: 'Tone 3', started_at: '2026-10-14T10:00:00', ended_at: null, first_mean: 0.5, best_mean: 0.8 }])
    const { unmount } = render(<MemoryRouter><Stats /></MemoryRouter>)
    expect(await screen.findByText('Tone 3', { selector: '[data-drill-label]' })).toBeInTheDocument()
    expect(screen.getByText('50 → 80')).toBeInTheDocument()
    unmount()
    render(<MemoryRouter><Stats /></MemoryRouter>)
    expect(await screen.findByText('No drills yet.')).toBeInTheDocument()
  })
})
