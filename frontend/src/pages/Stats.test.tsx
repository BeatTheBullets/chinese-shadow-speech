import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it, vi } from 'vitest'

const h = vi.hoisted(() => ({ stats: {
  activity: vi.fn(() => Promise.resolve({ days: [] })), sentences: vi.fn(() => Promise.resolve({ regressed: [], by_last: [] })),
  syllables: vi.fn(() => Promise.resolve({ syllables: [{ ch: '好', pinyin: 'hao', tone: 3, mean: 0.5, n: 20, trend: 0.2 }] })),
  tones: vi.fn(() => Promise.resolve({ tones: [{ tone: 3, mean: 0.55, n: 20 }], pairs: [{ prev_tone: 3, tone: 3, mean: 0.4, n: 6 }], weeks: [{ week: '2026-W41', tone: 3, mean: 0.55, n: 20 }] })),
} }))
vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api/client')>()), api: { stats: h.stats } }))
import Stats from './Stats'

describe('<Stats>', () => {
  it('shows characters with trend, tone means, the trend chart and the pair matrix', async () => {
    render(<MemoryRouter><Stats /></MemoryRouter>)
    expect(await screen.findByText('好')).toBeInTheDocument()
    expect(screen.getByText('↑ 20')).toBeInTheDocument()
    expect(screen.getByText(/Tone 3 \(low\)/)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /Tone scores per week/ })).toBeInTheDocument()
    expect(screen.getByTitle('after tone 3, tone 3: 40 (n 6)')).toBeInTheDocument()
  })
})
