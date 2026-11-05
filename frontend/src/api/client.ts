import type {
  ActivityStats, AnkiNotePayload, Attempt, CharacterStats, DrillFocus, DrillRecent, DrillSession, DrillSummary, FlowRun, Job, Lesson, LessonDetail, LessonStats, Mode, PracticeSession,
  Segment, SentenceStats, SoundStats, StatsOverview, Take, ToneStats, UnexportedItem, VoiceProfile,
} from './types'

// Same-origin in production (the backend serves the built SPA); the dev server talks to the backend directly.
const base: string = import.meta.env.VITE_API ?? (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '')

const modeQuery = (mode?: 'flow') => (mode ? `?mode=${mode}` : '')

// A non-2xx answer. `detail` is FastAPI's `{"detail": ...}` message when there is one, else the raw body.
export class ApiError extends Error {
  constructor(readonly status: number, statusText: string, body: string, readonly detail: string) {
    super(`${status} ${statusText}: ${body}`)
  }
}
function detailOf(body: string): string {
  try {
    const d = (JSON.parse(body) as { detail?: unknown }).detail
    if (typeof d === 'string') return d
  } catch { /* not JSON */ }
  return body
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${base}${path}`, init)
  if (!res.ok) { const body = await res.text(); throw new ApiError(res.status, res.statusText, body, detailOf(body)) }
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}
// Edit, split and merge re-cut a sentence's clip under the same id; a new revision gives its audio a fresh URL so
// neither the player's cache nor the browser's serves the old clip.
const clipRev = new Map<number, number>()

const json = (method: string, body: unknown): RequestInit => ({ method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })

export const api = {
  base,
  lessons: {
    list: () => req<Lesson[]>('/lessons'),
    get: (id: number) => req<LessonDetail>(`/lessons/${id}`),
    remove: (id: number) => req<void>(`/lessons/${id}`, { method: 'DELETE' }),
    patch: (id: number, body: { title?: string; speaker?: string }) => req<Lesson>(`/lessons/${id}`, json('PATCH', body)),
    upload: (file: File, opts: { subtitles?: File; title?: string; speaker?: string } = {}) => {
      const fd = new FormData()
      fd.append('file', file)
      if (opts.subtitles) fd.append('subtitles', opts.subtitles)
      fd.append('title', opts.title ?? file.name)
      fd.append('speaker', opts.speaker ?? '')
      return req<{ job_id: string; lesson_id: number }>('/lessons', { method: 'POST', body: fd })
    },
    ankiImport: (query_name: string, notes: AnkiNotePayload[]) =>
      req<{ jobs: { job_id: string; lesson_id: number; title: string }[] }>('/lessons/anki', json('POST', { query_name, notes })),
    youtube: (url: string) => req<{ job_id: string | null; lesson_id: number }>('/lessons/youtube', json('POST', { url })),
    rebuild: (id: number) => req<{ job_id: string; lesson_id: number }>(`/lessons/${id}/rebuild`, { method: 'POST' }),
    takes: (id: number) => req<{ takes: Take[] }>(`/lessons/${id}/takes`).then((r) => r.takes),
    flowRuns: (id: number) => req<{ runs: FlowRun[] }>(`/lessons/${id}/flow-runs`).then((r) => r.runs),
  },
  segments: {
    audioUrl: (id: number, fmt: 'opus' | 'wav' | 'mp3' = 'opus') => {
      const v = clipRev.get(id)
      return `${base}/segments/${id}/audio?fmt=${fmt}${v ? `&v=${v}` : ''}`
    },
    clipChanged: (id: number) => { clipRev.set(id, Math.max(Date.now(), (clipRev.get(id) ?? 0) + 1)) },
    patch: (id: number, body: { difficulty_flag?: boolean; text?: string; anki_note_id?: number }) => req<Segment>(`/segments/${id}`, json('PATCH', body)),
    resplit: (id: number, at_char_index: number) => req<Segment[]>(`/segments/${id}/resplit`, json('POST', { at_char_index })),
    mergeNext: (id: number) => req<Segment>(`/segments/${id}/merge-next`, { method: 'POST' }),
    attempts: (id: number) => req<Attempt[]>(`/segments/${id}/attempts`),
    postAttempt: (id: number, wav: Blob, opts: { session_id?: number; drill_session_id?: number; mode: Mode }) => {
      const fd = new FormData()
      fd.append('audio', new File([wav], 'attempt.wav', { type: 'audio/wav' }))
      fd.append('mode', opts.mode)
      if (opts.session_id != null) fd.append('session_id', String(opts.session_id))
      if (opts.drill_session_id != null) fd.append('drill_session_id', String(opts.drill_session_id))
      return req<Attempt>(`/segments/${id}/attempts`, { method: 'POST', body: fd })
    },
  },
  attempts: { audioUrl: (id: number) => `${base}/attempts/${id}/audio` },
  sessions: {
    create: (lesson_id: number, mode: Mode) => req<PracticeSession>('/sessions', json('POST', { lesson_id, mode })),
    end: (id: number) => req<PracticeSession>(`/sessions/${id}`, json('PATCH', { ended: true })),
  },
  drill: {
    focuses: () => req<{ focuses: DrillFocus[]; auto: { kind: string; key: string } | null }>('/drill/focuses'),
    start: (body: { kind: string; key: string; segment_ids?: number[] }) => req<DrillSession>('/drill/sessions', json('POST', body)),
    end: (id: number) => req<unknown>(`/drill/sessions/${id}`, json('PATCH', { ended: true })),
    summary: (id: number) => req<DrillSummary>(`/drill/sessions/${id}/summary`),
    recent: (limit = 10) => req<{ sessions: DrillRecent[] }>(`/drill/sessions?limit=${limit}`).then((r) => r.sessions),
  },
  jobs: {
    get: (id: string) => req<Job>(`/jobs/${id}`),
    events: (id: string, onEvent: (j: Job) => void, onError?: () => void): (() => void) => {
      const es = new EventSource(`${base}/jobs/${id}/events`)
      es.addEventListener('progress', (e) => {
        const j = JSON.parse((e as MessageEvent).data) as Job
        onEvent(j)
        if (j.status === 'done' || j.status === 'error') es.close()
      })
      es.onerror = () => { es.close(); onError?.() }
      return () => es.close()
    },
  },
  stats: {
    lesson: (id: number) => req<LessonStats>(`/lessons/${id}/stats`),
    overview: () => req<StatsOverview>('/api/stats/overview'),
    characters: (mode?: 'flow') => req<CharacterStats>(`/api/stats/characters${modeQuery(mode)}`),
    tones: (mode?: 'flow') => req<ToneStats>(`/api/stats/tones${modeQuery(mode)}`),
    sounds: (mode?: 'flow') => req<SoundStats>(`/api/stats/sounds${modeQuery(mode)}`),
    sentences: () => req<SentenceStats>('/api/stats/sentences'),
    activity: (days = 30) => req<ActivityStats>(`/api/stats/activity?days=${days}`),
  },
  voiceProfile: {
    get: () => req<VoiceProfile>('/voice-profile'),
    reset: () => req<void>('/voice-profile', { method: 'DELETE' }),
  },
  settings: {
    youtubeCookies: {
      get: () => req<{ present: boolean }>('/settings/youtube-cookies'),
      put: (file: File) => {
        const fd = new FormData()
        fd.append('file', file)
        return req<{ present: boolean }>('/settings/youtube-cookies', { method: 'PUT', body: fd })
      },
      remove: () => req<void>('/settings/youtube-cookies', { method: 'DELETE' }),
    },
  },
  review: {
    unexported: () => req<UnexportedItem[]>('/review/unexported'),
  },
}
