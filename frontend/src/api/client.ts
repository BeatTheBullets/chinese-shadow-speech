import type {
  ActivityStats, AnkiNotePayload, Attempt, Job, Lesson, LessonDetail, LessonStats, Mode, PracticeSession,
  Segment, SentenceStats, SyllableStats, ToneStats,
} from './types'

// Same-origin in production (the backend serves the built SPA); the dev server talks to the backend directly.
const base: string = import.meta.env.VITE_API ?? (import.meta.env.DEV ? 'http://127.0.0.1:8000' : '')

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${base}${path}`, init)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}: ${await res.text()}`)
  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}
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
  },
  segments: {
    audioUrl: (id: number, fmt: 'opus' | 'wav' | 'mp3' = 'opus') => `${base}/segments/${id}/audio?fmt=${fmt}`,
    patch: (id: number, body: { difficulty_flag?: boolean; text?: string }) => req<Segment>(`/segments/${id}`, json('PATCH', body)),
    resplit: (id: number, at_char_index: number) => req<Segment[]>(`/segments/${id}/resplit`, json('POST', { at_char_index })),
    mergeNext: (id: number) => req<Segment>(`/segments/${id}/merge-next`, { method: 'POST' }),
    attempts: (id: number) => req<Attempt[]>(`/segments/${id}/attempts`),
    postAttempt: (id: number, wav: Blob, opts: { session_id?: number; mode: Mode }) => {
      const fd = new FormData()
      fd.append('audio', new File([wav], 'attempt.wav', { type: 'audio/wav' }))
      fd.append('mode', opts.mode)
      if (opts.session_id != null) fd.append('session_id', String(opts.session_id))
      return req<Attempt>(`/segments/${id}/attempts`, { method: 'POST', body: fd })
    },
  },
  attempts: { audioUrl: (id: number) => `${base}/attempts/${id}/audio` },
  sessions: {
    create: (lesson_id: number, mode: Mode) => req<PracticeSession>('/sessions', json('POST', { lesson_id, mode })),
    end: (id: number) => req<PracticeSession>(`/sessions/${id}`, json('PATCH', { ended: true })),
  },
  jobs: {
    get: (id: string) => req<Job>(`/jobs/${id}`),
    events: (id: string, onEvent: (j: Job) => void): (() => void) => {
      const es = new EventSource(`${base}/jobs/${id}/events`)
      es.addEventListener('progress', (e) => {
        const j = JSON.parse((e as MessageEvent).data) as Job
        onEvent(j)
        if (j.status === 'done' || j.status === 'error') es.close()
      })
      es.onerror = () => es.close()
      return () => es.close()
    },
  },
  stats: {
    lesson: (id: number) => req<LessonStats>(`/lessons/${id}/stats`),
    activity: (days = 30) => req<ActivityStats>(`/stats/activity?days=${days}`),
    sentences: () => req<SentenceStats>('/stats/sentences'),
    syllables: () => req<SyllableStats>('/stats/syllables'),
    tones: () => req<ToneStats>('/stats/tones'),
  },
}
