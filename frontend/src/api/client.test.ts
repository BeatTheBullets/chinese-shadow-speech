import { describe, it, expect, vi, beforeEach } from 'vitest'
import { api, ApiError } from './client'

describe('api client', () => {
  beforeEach(() => { vi.restoreAllMocks() })

  it('GETs lessons from the base url', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify([{ id: 1 }]), { status: 200 }))
    const lessons = await api.lessons.list()
    expect(lessons).toEqual([{ id: 1 }])
    expect(fetchMock.mock.calls[0][0]).toBe(`${api.base}/lessons`)
  })

  it('throws with status text on error', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"detail":"nope"}', { status: 404 }))
    await expect(api.lessons.get(9)).rejects.toThrow(/404/)
  })

  it('errors carry the status and the backend detail', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"detail":"no next segment"}', { status: 409, statusText: 'Conflict' }))
    const e = await api.segments.mergeNext(3).catch((x) => x)
    expect(e).toBeInstanceOf(ApiError)
    expect(e).toMatchObject({ status: 409, detail: 'no next segment' })
    expect(e.message).toBe('409 Conflict: {"detail":"no next segment"}')
  })

  it('a changed clip gets a fresh audio URL', () => {
    expect(api.segments.audioUrl(41, 'mp3')).toBe(`${api.base}/segments/41/audio?fmt=mp3`)
    api.segments.clipChanged(41)
    const fresh = api.segments.audioUrl(41, 'mp3')
    expect(fresh).toMatch(/^.*\/segments\/41\/audio\?fmt=mp3&v=\d+$/)
    expect(api.segments.audioUrl(41)).toMatch(/fmt=opus&v=\d+$/)
    expect(api.segments.audioUrl(42)).toBe(`${api.base}/segments/42/audio?fmt=opus`)
  })

  it('builds multipart for attempts', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"id":3}', { status: 201 }))
    await api.segments.postAttempt(5, new Blob([new Uint8Array(4)], { type: 'audio/wav' }), { session_id: 2, mode: 'echo' })
    const body = fetchMock.mock.calls[0][1]!.body as FormData
    expect(body.get('mode')).toBe('echo')
    expect(body.get('session_id')).toBe('2')
    expect((body.get('audio') as File).type).toBe('audio/wav')
  })

  it("GETs a lesson's stored takes and Flow runs", async () => {
    const take = { segment_id: 3, attempt_id: 8, mode: 'echo', created_at: '2026-10-07T09:00:00Z', duration_s: 1.5 }
    const run = { started_at: '2026-10-07T09:00:00Z', ended_at: '2026-10-07T09:01:00Z', session_id: 2, items: [{ segment_id: 3, idx: 0, attempt_id: 8 }] }
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(new Response(JSON.stringify({ takes: [take] }), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ runs: [run] }), { status: 200 }))
    expect(await api.lessons.takes(4)).toEqual([take])
    expect(await api.lessons.flowRuns(4)).toEqual([run])
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual([`${api.base}/lessons/4/takes`, `${api.base}/lessons/4/flow-runs`])
  })

  it('stats endpoints live under /api/stats, with ?mode=flow only when asked', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(() => Promise.resolve(new Response('{}', { status: 200 })))
    await api.stats.overview()
    await api.stats.characters('flow')
    await api.stats.tones()
    expect(fetchMock.mock.calls.map((c) => c[0])).toEqual([
      `${api.base}/api/stats/overview`, `${api.base}/api/stats/characters?mode=flow`, `${api.base}/api/stats/tones`])
  })
})
