import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const h = vi.hoisted(() => ({ update: vi.fn() }))
vi.mock('../api/client', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api/client')>()), api: { app: { update: h.update } } }))
import UpdateBanner from './UpdateBanner'

const info = (over = {}) => ({ current: '1.0.0', latest: '1.1.0', url: 'https://example.test/r', newer: true, ...over })

describe('UpdateBanner', () => {
  beforeEach(() => { h.update.mockReset(); localStorage.clear() })
  afterEach(cleanup)

  it('renders nothing unless a newer version exists', async () => {
    h.update.mockResolvedValue(info({ newer: false }))
    const { container } = render(<UpdateBanner />)
    await waitFor(() => expect(h.update).toHaveBeenCalled())
    expect(container.textContent).toBe('')
  })

  it('renders nothing when the request fails', async () => {
    h.update.mockRejectedValue(new Error('x'))
    const { container } = render(<UpdateBanner />)
    await waitFor(() => expect(h.update).toHaveBeenCalled())
    expect(container.textContent).toBe('')
  })

  it('shows the version and a link that opens in a new tab', async () => {
    h.update.mockResolvedValue(info())
    render(<UpdateBanner />)
    expect(await screen.findByText(/A new version \(1\.1\.0\) is available/)).toBeTruthy()
    const a = screen.getByRole('link', { name: 'Download' })
    expect(a.getAttribute('href')).toBe('https://example.test/r')
    expect(a.getAttribute('target')).toBe('_blank')
  })

  it('dismiss hides it for that version only', async () => {
    h.update.mockResolvedValue(info())
    const { unmount } = render(<UpdateBanner />)
    fireEvent.click(await screen.findByRole('button', { name: 'Dismiss' }))
    expect(screen.queryByText(/A new version/)).toBeNull()
    unmount()
    render(<UpdateBanner />)
    await waitFor(() => expect(h.update).toHaveBeenCalledTimes(2))
    expect(screen.queryByText(/A new version/)).toBeNull()
    cleanup()
    h.update.mockResolvedValue(info({ latest: '1.2.0' }))
    render(<UpdateBanner />)
    expect(await screen.findByText(/A new version \(1\.2\.0\)/)).toBeTruthy()
  })
})
