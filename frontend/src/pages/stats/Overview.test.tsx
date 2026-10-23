import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { StatsOverview } from '../../api/types'

const h = vi.hoisted(() => ({ overview: vi.fn() }))
vi.mock('../../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../../api/client')>()), api: { stats: { overview: h.overview } } }))
import Overview from './Overview'

const sc = (value: number | null, last7: number | null, prev7: number | null, n: number) => ({ value, last7, prev7, n })
const full: StatsOverview = {
  scores: { characters: sc(0.61, 0.6, 0.55, 40), tones: sc(0.73, 0.74, 0.7, 312), sounds: sc(0.82, 0.8, 0.8, 150) },
  flow: { characters: sc(0.5, null, null, 12), tones: sc(0.66, 0.7, 0.6, 90), sounds: sc(0.9, 0.9, 0.9, 60) },
  weakest: {
    characters: [{ ch: '好', pinyin: 'hǎo', score: 0.31, tone_right: 0.3, sound_right: 0.5, takes: 9, trend: null }],
    tones: [{ kind: 'pair', key: '3-3', label: '3 → 3', mean: 0.44, n: 12 }],
    sounds: [{ key: 'uo>ou', label: 'uo said as ou', slips: 22, chances: 45, rate: 0.49, hard: true }],
  },
  activity: { minutes: 41.6, takes: 120, days: 5 },
  sentences: [{ segment_id: 1, lesson_id: 7, lesson_title: 'Cafe talk', idx: 3, text: '我想喝咖啡', last: 0.38, best: 0.8, attempts: 4, regressed: true }],
  drills: [{ id: 1, kind: 'tone', key: '3', label: 'Tone 3', started_at: '2026-10-14T10:00:00', ended_at: null, first_mean: 0.5, best_mean: 0.8 }],
}
const zero = { value: null, last7: null, prev7: null, n: 0 }
const empty: StatsOverview = {
  scores: { characters: zero, tones: zero, sounds: zero }, flow: { characters: zero, tones: zero, sounds: zero },
  weakest: { characters: [], tones: [], sounds: [] }, activity: { minutes: 0, takes: 0, days: 0 }, sentences: [], drills: [],
}

const Where = () => { const l = useLocation(); return <p data-testid="where">{l.pathname + l.search}</p> }
const renderIt = () => render(<MemoryRouter><Routes><Route path="/" element={<Overview />} /><Route path="/practice/:id" element={<Where />} /></Routes></MemoryRouter>)

describe('<Overview>', () => {
  beforeEach(() => { h.overview.mockReset() })

  it('shows the three scores with change and n', async () => {
    h.overview.mockResolvedValue(full)
    renderIt()
    expect(await screen.findByText('73')).toBeInTheDocument()
    expect(screen.getByText('▲ 4')).toBeInTheDocument()
    expect(screen.getByText('312 syllables')).toBeInTheDocument()
  })

  it('shows the weakest of each area', async () => {
    h.overview.mockResolvedValue(full)
    renderIt()
    expect(await screen.findByText('好')).toBeInTheDocument()
    expect(screen.getByText('3 → 3')).toBeInTheDocument()
    expect(screen.getByText('uo said as ou')).toBeInTheDocument()
    expect(screen.getByText('22 of 45')).toBeInTheDocument()
    expect(screen.getByText('Tone 3 50 → 80')).toBeInTheDocument()
    expect(screen.getByText('42 min · 120 takes · 5 of 7 days')).toBeInTheDocument()
  })

  it('a sentence opens in Practice', async () => {
    h.overview.mockResolvedValue(full)
    renderIt()
    fireEvent.click(await screen.findByText('我想喝咖啡'))
    expect((await screen.findByTestId('where')).textContent).toBe('/practice/7?idx=3')
  })

  it('the Flow widget links to the Flow-only details', async () => {
    h.overview.mockResolvedValue(full)
    renderIt()
    await screen.findByText('73')
    const links = screen.getAllByRole('link').map((a) => a.getAttribute('href'))
    expect(links).toContain('/stats/tones?mode=flow')
    expect(links).toContain('/stats/characters?mode=flow')
    expect(links).toContain('/stats/sounds?mode=flow')
  })

  it('empty overview', async () => {
    h.overview.mockResolvedValue(empty)
    renderIt()
    expect(await screen.findByText('Practise a few sentences to see your scores.')).toBeInTheDocument()
    expect(document.querySelectorAll('[data-score]')).toHaveLength(3)
    document.querySelectorAll('[data-score]').forEach((t) => expect(t.textContent).toBe('—'))
  })

  it('load error', async () => {
    h.overview.mockImplementation(() => Promise.reject(new Error('boom')))
    renderIt()
    expect(await screen.findByText(/Could not load stats/)).toBeInTheDocument()
  })
})
