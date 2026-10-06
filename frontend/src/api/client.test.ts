import { describe, it, expect, vi, beforeEach } from 'vitest'
import { api } from './client'

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

  it('builds multipart for attempts', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{"id":3}', { status: 201 }))
    await api.segments.postAttempt(5, new Blob([new Uint8Array(4)], { type: 'audio/wav' }), { session_id: 2, mode: 'echo' })
    const body = fetchMock.mock.calls[0][1]!.body as FormData
    expect(body.get('mode')).toBe('echo')
    expect(body.get('session_id')).toBe('2')
    expect((body.get('audio') as File).type).toBe('audio/wav')
  })
})
