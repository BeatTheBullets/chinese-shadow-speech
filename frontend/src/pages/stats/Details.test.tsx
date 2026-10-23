import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const char = { ch: '好', pinyin: 'hǎo', score: 0.5, tone_right: 0.5, sound_right: 0.6, takes: 20, trend: 0.2 }
const h = vi.hoisted(() => ({ stats: {
  activity: vi.fn(), sentences: vi.fn(), characters: vi.fn(), tones: vi.fn(), sounds: vi.fn(),
}, drill: { recent: vi.fn() } }))
vi.mock('../../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../../api/client')>()), api: { stats: h.stats, drill: h.drill } }))
import Activity from './Activity'
import Characters from './Characters'
import Drills from './Drills'
import Sentences from './Sentences'
import Sounds from './Sounds'
import Tones from './Tones'

const Where = () => { const l = useLocation(); return <p data-testid="where">{l.pathname + l.search}</p> }
const at = (path: string) => render(
  <MemoryRouter initialEntries={[path]}><Routes>
    <Route path="/stats/characters" element={<Characters />} /><Route path="/stats/tones" element={<Tones />} />
    <Route path="/stats/sounds" element={<Sounds />} /><Route path="/stats/sentences" element={<Sentences />} />
    <Route path="/stats/activity" element={<Activity />} /><Route path="/stats/drills" element={<Drills />} />
    <Route path="/drill" element={<Where />} /><Route path="/practice/:id" element={<Where />} /><Route path="/stats" element={<Where />} />
  </Routes></MemoryRouter>)

beforeEach(() => {
  Object.values(h.stats).forEach((f) => f.mockReset()); h.drill.recent.mockReset()
  h.stats.characters.mockResolvedValue({ characters: [char] })
  h.stats.tones.mockResolvedValue({ tones: [{ tone: 3, mean: 0.55, n: 20 }], pairs: [{ prev_tone: 3, tone: 3, mean: 0.4, n: 6 }], weeks: [{ week: '2026-W41', tone: 3, mean: 0.55, n: 20 }] })
  h.stats.sounds.mockResolvedValue({ sounds: [{ key: 'ch>c', label: 'ch said as c', slips: 2, chances: 10, rate: 0.2, hard: true }], weeks: [] })
  h.stats.sentences.mockResolvedValue({ sentences: [] })
  h.stats.activity.mockResolvedValue({ days: [] })
  h.drill.recent.mockResolvedValue([])
})

describe('details pages', () => {
  it.each([
    ['/stats/tones', 'Drill tone 3', '/drill?kind=tone&key=3'],
    ['/stats/characters', 'Drill 好', '/drill?kind=char&key=%E5%A5%BD'],
    ['/stats/tones', 'Drill tone pair 3→3', '/drill?kind=pair&key=3-3'],
    ['/stats/sounds', 'Drill ch said as c', '/drill?kind=sound&key=ch%3Ec'],
  ])('%s: "%s" navigates to the drill page', async (path, name, url) => {
    at(path)
    fireEvent.click(await screen.findByRole('button', { name }))
    expect((await screen.findByTestId('where')).textContent).toBe(url)
  })

  it('characters page lists rows with trend', async () => {
    at('/stats/characters')
    expect(await screen.findByText('好')).toBeInTheDocument()
    expect(screen.getByText('hǎo')).toBeInTheDocument()
    expect(screen.getByText('↑ 20')).toBeInTheDocument()
    expect(screen.getByText(/sound 60/)).toBeInTheDocument()
  })

  it('characters page shows a dash for a missing sound score', async () => {
    h.stats.characters.mockResolvedValue({ characters: [{ ...char, sound_right: null }] })
    at('/stats/characters')
    expect(await screen.findByText(/sound —/)).toBeInTheDocument()
  })

  it('flow-only header links back to all takes', async () => {
    at('/stats/characters?mode=flow')
    expect(await screen.findByText('Flow only')).toBeInTheDocument()
    expect(h.stats.characters).toHaveBeenCalledWith('flow')
    expect(screen.getByRole('link', { name: 'All takes' })).toHaveAttribute('href', '/stats/characters')
  })

  it('sounds page marks hard sounds and says what is not checked', async () => {
    at('/stats/sounds')
    expect(await screen.findByText('ch said as c')).toBeInTheDocument()
    expect(screen.getByText('hard')).toBeInTheDocument()
    expect(screen.getByText('Not checked yet: j/q/x mix-ups and breathy vs plain consonants (b/p, d/t, g/k, j/q, zh/ch, z/c).')).toBeInTheDocument()
  })

  it('sentences page shows text, regressed badge, and opens Practice', async () => {
    h.stats.sentences.mockResolvedValue({ sentences: [{ segment_id: 1, lesson_id: 7, lesson_title: 'Cafe talk', idx: 3, text: '我想喝咖啡', last: 0.38, best: 0.8, attempts: 4, regressed: true }] })
    at('/stats/sentences')
    expect(await screen.findByText('我想喝咖啡')).toBeInTheDocument()
    expect(screen.getByText('Cafe talk')).toBeInTheDocument()
    expect(screen.getByText('regressed')).toBeInTheDocument()
    expect(screen.getByText('last 38')).toBeInTheDocument()
    expect(screen.getByText('best 80')).toBeInTheDocument()
    expect(screen.getByText('4 takes')).toBeInTheDocument()
    fireEvent.click(screen.getByText('我想喝咖啡'))
    expect((await screen.findByTestId('where')).textContent).toBe('/practice/7?idx=3')
  })

  it('drills page lists recent drills with first → best, or says there are none', async () => {
    h.drill.recent.mockResolvedValueOnce([{ id: 1, kind: 'tone', key: '3', label: 'Tone 3', started_at: '2026-10-14T10:00:00', ended_at: null, first_mean: 0.5, best_mean: 0.8 }])
    const { unmount } = at('/stats/drills')
    expect(await screen.findByText('Tone 3', { selector: '[data-drill-label]' })).toBeInTheDocument()
    expect(screen.getByText('50 → 80')).toBeInTheDocument()
    expect(screen.getByText('Last 10 drills')).toBeInTheDocument()
    unmount()
    at('/stats/drills')
    expect(await screen.findByText('No drills yet.')).toBeInTheDocument()
  })

  it('activity page shows its window', async () => {
    at('/stats/activity')
    expect(await screen.findByText('No practice yet.')).toBeInTheDocument()
    expect(screen.getByText('Last 30 days')).toBeInTheDocument()
  })

  it('back link returns to the overview', async () => {
    at('/stats/tones')
    expect(await screen.findByRole('link', { name: '‹ Stats' })).toHaveAttribute('href', '/stats')
  })
})
