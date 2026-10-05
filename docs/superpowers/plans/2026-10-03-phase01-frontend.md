# Phase 1 Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The React practice app for Phase 1: library with upload and Anki import, the practice page with stage + drawer, two-track feedback in its unscored state, Echo / Chorus / Flow / Guided modes, Anki export, Review and Stats pages, Yomitan-compatible rendering.

**Architecture:** Vite + React + TypeScript SPA talking to the backend from the plan `2026-10-03-phase01-backend.md` and to AnkiConnect directly from the browser. Audio playback uses `<audio>` elements with `preservesPitch`; recording uses an `AudioWorklet` capturing PCM, encoded to 16 kHz WAV in the browser. All timing logic (flow schedule, slice ranges, VAD, state machines) lives in pure modules under `src/lib` with unit tests; components are thin.

**Tech Stack:** Node 20, Vite 5, React 18, TypeScript, Tailwind 3, react-router 6, zustand, vitest + @testing-library/react + jsdom, @fontsource/noto-sans-sc, @fontsource-variable/inter.

**Spec:** `docs/superpowers/specs/2026-10-03-shadowing-tool-design.md` §6, §7, §8.1–8.2

## Global Constraints

- Desktop first; dark studio theme only (§7.6): near-black backgrounds, reference blue `#8fb3d9`, you amber `#e0a33a`, score green `#4caf7d` / orange `#e0a33a` / red `#d9534f`, unvoiced grey.
- Hanzi in Noto Sans SC; pinyin and UI in Inter.
- Yomitan rule (§7.7): sentence rendered as one `<p lang="zh">` of `<ruby>word<rt>pinyin</rt></ruby>` per **word**; pinyin toggle hides `<rt>` with CSS only; no per-character spans in the sentence; no shadow DOM; no canvas text for the sentence; no `user-select: none` on it.
- Recording is WAV PCM16 at 16 kHz produced in the browser; never `MediaRecorder`.
- Playback speed 0.6–1.0, one-tap 0.75, via `HTMLMediaElement.preservesPitch = true`.
- Text auto-hides while recording when the setting is on (default on). Session timer amber at 20 min. "Move on" hint after 4 attempts.
- AnkiConnect calls go from the browser to `http://127.0.0.1:8765` (configurable); nothing is written back to Anki except explicit exports.
- Backend base URL: `import.meta.env.VITE_API ?? "http://127.0.0.1:8000"`.

## Review Focus

1. Microphone permission denied or no input device: Enter must show a readable error in the transport bar and leave the state machine in `idle`, not stuck in `recording`. Test added to Task 9 (`echoReducer` handles `RECORD_FAILED`).
2. Flow mode where the user stops midway: already-played sentences must be sliced and submitted, the unfinished one dropped. Test added to Task 10 (`sliceRangesFromActual` ignores entries without `playEnd`).
3. A lesson whose segment has no `words_json` (error during enrich, or a segment edited to punctuation only) must render the raw text as one ruby-less text node, not crash. Test added to Task 5.
4. An Anki note type whose mapped audio field has no `[sound:]` tag must be skipped with a count shown, not abort the whole import. Test added to Task 2 (`notesToImportPayload` returns `skipped`).
5. Keyboard shortcuts must not fire while typing in the edit-text dialog or any input. Test added to Task 9 (`shouldHandleKey(target)`).

---

### Task 1: Scaffold, theme, API client, test harness

**Files:**
- Create: `frontend/` via Vite, `frontend/tailwind.config.ts`, `frontend/postcss.config.js`, `frontend/src/index.css`, `frontend/src/api/types.ts`, `frontend/src/api/client.ts`, `frontend/src/main.tsx`, `frontend/src/App.tsx`, `frontend/src/test/setup.ts`, `frontend/src/api/client.test.ts`, `frontend/vite.config.ts`

**Interfaces:**
- `api/types.ts`: `Lesson, LessonDetail, Segment, Word, Syllable, Attempt, PracticeSession, Job` mirroring backend `schemas.py` and `words_json` (`Word { word, pinyin, tones, char_from, char_to, syllables: Syllable[] }`, `Syllable { ch, pinyin, pinyin_toneless, tone }`).
- `api/client.ts`: `api.lessons.list()`, `.get(id)`, `.upload(file, {subtitles?, title?, speaker?})`, `.ankiImport(payload)`, `.remove(id)`, `.patch(id, body)`; `api.segments.audioUrl(id, fmt)`, `.patch(id, body)`, `.resplit(id, at)`, `.mergeNext(id)`, `.attempts(id)`, `.postAttempt(id, wavBlob, {session_id?, mode})`; `api.sessions.create(lesson_id, mode)`, `.end(id)`; `api.jobs.get(id)`, `.events(id, onEvent) -> () => void`; `api.stats.lesson(id)`, `.activity(days)`, `.sentences()`, `.syllables()`, `.tones()`; `api.base`.

- [ ] **Step 1: Scaffold**

```bash
cd ~/shadow-speech && npm create vite@latest frontend -- --template react-ts
cd frontend && npm install
npm install react-router-dom zustand @fontsource/noto-sans-sc @fontsource-variable/inter
npm install -D tailwindcss@3 postcss autoprefixer vitest jsdom @testing-library/react @testing-library/jest-dom @testing-library/user-event @types/node
npx tailwindcss init -p --ts
```

`frontend/vite.config.ts`:
```ts
/// <reference types="vitest" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, strictPort: true },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/test/setup.ts'] },
})
```

`frontend/src/test/setup.ts`:
```ts
import '@testing-library/jest-dom/vitest'
```

`frontend/tailwind.config.ts`:
```ts
import type { Config } from 'tailwindcss'
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0b0e12', panel: '#111418', panel2: '#161b21', line: '#2a3139',
        fg: '#cfd6dd', fgdim: '#7c8793', fghi: '#f2f5f7',
        ref: '#8fb3d9', you: '#e0a33a', ok: '#4caf7d', warn: '#e0a33a', bad: '#d9534f', accent: '#4a86c8',
      },
      fontFamily: { hanzi: ['"Noto Sans SC"', 'sans-serif'], ui: ['"Inter Variable"', 'system-ui', 'sans-serif'] },
    },
  },
  plugins: [],
} satisfies Config
```

`frontend/src/index.css`:
```css
@import '@fontsource/noto-sans-sc/400.css';
@import '@fontsource/noto-sans-sc/500.css';
@import '@fontsource-variable/inter';
@tailwind base; @tailwind components; @tailwind utilities;
html, body, #root { height: 100%; }
body { @apply bg-bg text-fg font-ui; }
.sentence { @apply font-hanzi text-fghi text-center leading-snug; }
.sentence.hide-pinyin rt { display: none; }
.sentence rt { @apply text-ref font-ui text-sm tracking-wide; }
.cell-ok { @apply bg-[#17442d] border-[#1f5c3c]; }
.cell-warn { @apply bg-[#4d3a12] border-[#6b5219]; }
.cell-bad { @apply bg-[#4a1d22] border-[#6b2a31]; }
.cell-unvoiced { @apply bg-[#1a1f26] border-line; }
.cell-neutral { @apply bg-panel2 border-line; }
```

Add `"test": "vitest"` to `package.json` scripts.

- [ ] **Step 2: Failing test for the API client**

`frontend/src/api/client.test.ts`:
```ts
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
```

- [ ] **Step 3: Run to verify fail**

Run: `cd frontend && npx vitest run src/api`
Expected: FAIL, cannot resolve `./client`

- [ ] **Step 4: Implement types and client**

`frontend/src/api/types.ts`:
```ts
export interface Syllable { ch: string; pinyin: string; pinyin_toneless: string; tone: number }
export interface Word { word: string; pinyin: string; tones: number[]; char_from: number; char_to: number; syllables: Syllable[] }
export interface AlignSpan { ch: string; start: number; end: number; conf: number }
export interface Segment {
  id: number; lesson_id: number; idx: number; start_s: number; end_s: number; text: string
  translation: string | null; words_json: Word[] | null; ref_alignment_json: AlignSpan[] | null
  difficulty_flag: boolean; anki_note_id: number | null
  last_score: number | null; best_score: number | null; attempts: number
}
export interface Lesson {
  id: number; title: string; speaker: string; source_type: 'upload' | 'youtube' | 'anki'; source_ref: string
  duration_s: number; created_at: string; status: 'queued' | 'processing' | 'ready' | 'error'; error: string | null
  segment_count: number; practised_count: number; mean_last_score: number | null
}
export interface LessonDetail extends Lesson { segments: Segment[] }
export interface Attempt { id: number; segment_id: number; session_id: number | null; created_at: string; mode: string; duration_s: number; score_json: Record<string, unknown> | null }
export interface PracticeSession { id: number; lesson_id: number; mode: string; started_at: string; ended_at: string | null; attempts_count: number }
export interface Job { id: string; stage: string; fraction: number; status: 'queued' | 'running' | 'done' | 'error'; error: string | null; lesson_id: number | null }
export type Mode = 'echo' | 'chorus' | 'flow' | 'guided'
export interface AnkiNotePayload { note_id: number; text: string; translation: string | null; source: string | null; url: string | null; audio_b64: string; filename: string }
```

`frontend/src/api/client.ts`:
```ts
import type { Attempt, Job, Lesson, LessonDetail, Mode, PracticeSession, Segment, AnkiNotePayload } from './types'

const base: string = (import.meta as any).env?.VITE_API ?? 'http://127.0.0.1:8000'

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
    lesson: (id: number) => req<{ segments: { segment_id: number; idx: number; last: number | null; best: number | null; attempts: number; trend: number[] }[]; sessions: { session_id: number; started_at: string; mean: number | null }[] }>(`/lessons/${id}/stats`),
    activity: (days = 30) => req<{ days: { date: string; minutes: number; attempts: number }[] }>(`/stats/activity?days=${days}`),
    sentences: () => req<{ regressed: unknown[]; by_last: unknown[] }>('/stats/sentences'),
    syllables: () => req<{ syllables: { pinyin: string; tone: number; mean: number; n: number }[] }>('/stats/syllables'),
    tones: () => req<{ tones: { tone: number; mean: number; n: number }[]; pairs: { prev_tone: number; tone: number; mean: number; n: number }[] }>('/stats/tones'),
  },
}
```

`frontend/src/App.tsx` (routes filled by later tasks):
```tsx
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Navigate to="/library" replace />} />
        <Route path="*" element={<div className="p-8 text-fgdim">Not found</div>} />
      </Routes>
    </BrowserRouter>
  )
}
```

`frontend/src/main.tsx`: standard Vite entry importing `./index.css` and rendering `<App />`.

- [ ] **Step 5: Run tests and the dev build**

Run: `cd frontend && npx vitest run && npm run build`
Expected: 3 tests pass; build succeeds.

- [ ] **Step 6: Commit**

```bash
cd ~/shadow-speech && git add frontend && git commit -m "feat(frontend): scaffold, dark theme, typed API client"
```

---

### Task 2: AnkiConnect client and import payload builder

**Files:**
- Create: `frontend/src/anki/client.ts`, `frontend/src/anki/import.ts`, `frontend/src/anki/client.test.ts`, `frontend/src/anki/import.test.ts`

**Interfaces:**
- `client.ts`: `ankiRequest<T>(url, action, params?) -> Promise<T>`; `anki(url)` returning `{ requestPermission(), deckNames(), modelNames(), modelFieldNames(model), findNotes(query), notesInfo(ids), retrieveMediaFile(filename), addNote(note) }`; `NoteInfo { noteId, modelName, tags, fields: Record<string,{value:string,order:number}> }`.
- `import.ts`: `FieldMapping { sentence: string; audio: string; translation?: string; source?: string; url?: string }`; `parseSoundTag(fieldValue) -> string | null` (first tag); `stripHtml(s)`; `notesToImportPayload(notes: NoteInfo[], mapping, fetchMedia: (name) => Promise<string | false>) -> Promise<{ payload: AnkiNotePayload[]; skipped: number }>`.

- [ ] **Step 1: Failing tests**

`frontend/src/anki/client.test.ts`:
```ts
import { describe, it, expect, vi } from 'vitest'
import { ankiRequest, anki } from './client'

describe('ankiRequest', () => {
  it('posts action/version/params and unwraps result', async () => {
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ result: ['Default'], error: null })))
    const r = await ankiRequest<string[]>('http://127.0.0.1:8765', 'deckNames')
    expect(r).toEqual(['Default'])
    expect(JSON.parse(f.mock.calls[0][1]!.body as string)).toEqual({ action: 'deckNames', version: 6, params: {} })
  })
  it('throws on error field', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ result: null, error: 'bad' })))
    await expect(anki('http://x').findNotes('deck:X')).rejects.toThrow('bad')
  })
})
```

`frontend/src/anki/import.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { parseSoundTag, stripHtml, notesToImportPayload } from './import'

const mapping = { sentence: 'Sentence', audio: 'Audio', translation: 'Meaning', source: 'Source' }
const note = (id: number, fields: Record<string, string>) => ({
  noteId: id, modelName: 'Mining', tags: [], fields: Object.fromEntries(Object.entries(fields).map(([k, v], i) => [k, { value: v, order: i }])),
})

describe('import helpers', () => {
  it('parses first sound tag', () => {
    expect(parseSoundTag('[sound:a.mp3][sound:b.mp3]')).toBe('a.mp3')
    expect(parseSoundTag('nothing')).toBeNull()
  })
  it('strips html', () => {
    expect(stripHtml('<div>你好<br>世界</div>&nbsp;')).toBe('你好 世界')
  })
  it('builds payload and skips notes without audio', async () => {
    const notes = [
      note(1, { Sentence: '<b>你好。</b>', Audio: '[sound:a.mp3]', Meaning: 'Hi', Source: 'v1.mp4 00:00:01.000' }),
      note(2, { Sentence: '再见。', Audio: '', Meaning: '', Source: '' }),
    ]
    const { payload, skipped } = await notesToImportPayload(notes, mapping, async (n) => (n === 'a.mp3' ? 'QUJD' : false))
    expect(skipped).toBe(1)
    expect(payload).toEqual([{ note_id: 1, text: '你好。', translation: 'Hi', source: 'v1.mp4 00:00:01.000', url: null, audio_b64: 'QUJD', filename: 'a.mp3' }])
  })
})
```

- [ ] **Step 2: Run to verify fail**

Run: `cd frontend && npx vitest run src/anki`
Expected: FAIL

- [ ] **Step 3: Implement**

`frontend/src/anki/client.ts`:
```ts
export interface NoteInfo { noteId: number; modelName: string; tags: string[]; fields: Record<string, { value: string; order: number }> }
export interface AddNote {
  deckName: string; modelName: string; fields: Record<string, string>; tags: string[]
  options?: { allowDuplicate: boolean; duplicateScope: 'deck' | 'collection' }
  audio?: { filename: string; data: string; fields: string[] }[]
}

export async function ankiRequest<T>(url: string, action: string, params: Record<string, unknown> = {}): Promise<T> {
  const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, version: 6, params }) })
  const data = (await res.json()) as { result: T; error: string | null }
  if (data.error) throw new Error(data.error)
  return data.result
}

export const anki = (url: string) => ({
  requestPermission: () => ankiRequest<{ permission: 'granted' | 'denied' }>(url, 'requestPermission'),
  deckNames: () => ankiRequest<string[]>(url, 'deckNames'),
  modelNames: () => ankiRequest<string[]>(url, 'modelNames'),
  modelFieldNames: (modelName: string) => ankiRequest<string[]>(url, 'modelFieldNames', { modelName }),
  findNotes: (query: string) => ankiRequest<number[]>(url, 'findNotes', { query }),
  notesInfo: (notes: number[]) => ankiRequest<NoteInfo[]>(url, 'notesInfo', { notes }),
  retrieveMediaFile: (filename: string) => ankiRequest<string | false>(url, 'retrieveMediaFile', { filename }),
  addNote: (note: AddNote) => ankiRequest<number>(url, 'addNote', { note }),
})
```

`frontend/src/anki/import.ts`:
```ts
import type { AnkiNotePayload } from '../api/types'
import type { NoteInfo } from './client'

export interface FieldMapping { sentence: string; audio: string; translation?: string; source?: string; url?: string }

export function parseSoundTag(v: string): string | null {
  const m = /\[sound:([^\]]+)\]/.exec(v ?? '')
  return m ? m[1] : null
}

export function stripHtml(s: string): string {
  const withBreaks = (s ?? '').replace(/<br\s*\/?>/gi, ' ').replace(/<[^>]+>/g, '')
  const el = document.createElement('textarea')
  el.innerHTML = withBreaks
  return el.value.replace(/ /g, ' ').replace(/\s+/g, ' ').trim()
}

const field = (n: NoteInfo, name?: string) => (name && n.fields[name] ? n.fields[name].value : '')

export async function notesToImportPayload(
  notes: NoteInfo[], mapping: FieldMapping, fetchMedia: (filename: string) => Promise<string | false>,
): Promise<{ payload: AnkiNotePayload[]; skipped: number }> {
  const payload: AnkiNotePayload[] = []
  let skipped = 0
  for (const n of notes) {
    const filename = parseSoundTag(field(n, mapping.audio))
    const text = stripHtml(field(n, mapping.sentence).replace(/\[sound:[^\]]*\]/g, ''))
    const audio_b64 = filename ? await fetchMedia(filename) : false
    if (!filename || !text || audio_b64 === false) { skipped++; continue }
    payload.push({
      note_id: n.noteId, text, translation: stripHtml(field(n, mapping.translation)) || null,
      source: stripHtml(field(n, mapping.source)) || null, url: field(n, mapping.url) || null, audio_b64, filename,
    })
  }
  return { payload, skipped }
}
```

- [ ] **Step 4: Run tests**

Run: `cd frontend && npx vitest run src/anki`
Expected: 5 pass

- [ ] **Step 5: Commit**

```bash
git add frontend/src/anki && git commit -m "feat(frontend): AnkiConnect client and import payload builder"
```

---

### Task 3: Settings store and Settings page

**Files:**
- Create: `frontend/src/store/settings.ts`, `frontend/src/pages/Settings.tsx`, `frontend/src/store/settings.test.ts`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- `useSettings` (zustand, persisted to `localStorage` key `shadow.settings`): `{ ankiUrl, importQueries: { name, query, mapping: FieldMapping }[], exportNote: { deckName, modelName, fields: { sentence, pinyin?, translation?, audio } } | null, languageParent: string | null, practice: { hideTextWhileRecording, chorusPasses, flowGapFactor, moveOnAfter, defaultRate }, set(partial), addQuery(q), removeQuery(name), textPrefs: Record<lessonId, { hanzi, pinyin, translation }>, setTextPrefs(lessonId, prefs) }`.
- Defaults: `ankiUrl "http://127.0.0.1:8765"`, `practice { hideTextWhileRecording: true, chorusPasses: 5, flowGapFactor: 1.1, moveOnAfter: 4, defaultRate: 1.0 }`.

- [ ] **Step 1: Failing test**

`frontend/src/store/settings.test.ts`:
```ts
import { describe, it, expect, beforeEach } from 'vitest'
import { useSettings } from './settings'

describe('settings store', () => {
  beforeEach(() => { localStorage.clear(); useSettings.getState().reset() })
  it('has defaults', () => {
    const s = useSettings.getState()
    expect(s.ankiUrl).toBe('http://127.0.0.1:8765')
    expect(s.practice.chorusPasses).toBe(5)
  })
  it('persists queries and text prefs', () => {
    useSettings.getState().addQuery({ name: 'Mining', query: 'deck:Mining', mapping: { sentence: 'Sentence', audio: 'Audio' } })
    useSettings.getState().setTextPrefs(7, { hanzi: true, pinyin: false, translation: false })
    const raw = JSON.parse(localStorage.getItem('shadow.settings')!)
    expect(raw.state.importQueries[0].name).toBe('Mining')
    expect(raw.state.textPrefs['7'].pinyin).toBe(false)
  })
})
```

- [ ] **Step 2: Run to verify fail**

Run: `cd frontend && npx vitest run src/store`
Expected: FAIL

- [ ] **Step 3: Implement store**

`frontend/src/store/settings.ts`:
```ts
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { FieldMapping } from '../anki/import'

export interface ImportQuery { name: string; query: string; mapping: FieldMapping }
export interface ExportNote { deckName: string; modelName: string; fields: { sentence: string; pinyin?: string; translation?: string; audio: string } }
export interface TextPrefs { hanzi: boolean; pinyin: boolean; translation: boolean }
export interface PracticePrefs { hideTextWhileRecording: boolean; chorusPasses: number; flowGapFactor: number; moveOnAfter: number; defaultRate: number }

interface SettingsState {
  ankiUrl: string
  importQueries: ImportQuery[]
  exportNote: ExportNote | null
  languageParent: string | null
  practice: PracticePrefs
  textPrefs: Record<string, TextPrefs>
  set: (p: Partial<Omit<SettingsState, 'set' | 'addQuery' | 'removeQuery' | 'setTextPrefs' | 'reset'>>) => void
  addQuery: (q: ImportQuery) => void
  removeQuery: (name: string) => void
  setTextPrefs: (lessonId: number, prefs: TextPrefs) => void
  reset: () => void
}

const defaults = {
  ankiUrl: 'http://127.0.0.1:8765',
  importQueries: [] as ImportQuery[],
  exportNote: null as ExportNote | null,
  languageParent: null as string | null,
  practice: { hideTextWhileRecording: true, chorusPasses: 5, flowGapFactor: 1.1, moveOnAfter: 4, defaultRate: 1.0 },
  textPrefs: {} as Record<string, TextPrefs>,
}

export const useSettings = create<SettingsState>()(persist((set) => ({
  ...defaults,
  set: (p) => set(p),
  addQuery: (q) => set((s) => ({ importQueries: [...s.importQueries.filter((x) => x.name !== q.name), q] })),
  removeQuery: (name) => set((s) => ({ importQueries: s.importQueries.filter((x) => x.name !== name) })),
  setTextPrefs: (lessonId, prefs) => set((s) => ({ textPrefs: { ...s.textPrefs, [String(lessonId)]: prefs } })),
  reset: () => set(defaults),
}), { name: 'shadow.settings' }))

export const defaultTextPrefs: TextPrefs = { hanzi: true, pinyin: true, translation: false }
```

- [ ] **Step 4: Settings page**

`frontend/src/pages/Settings.tsx`:
```tsx
import { useEffect, useState } from 'react'
import { anki } from '../anki/client'
import { useSettings } from '../store/settings'

export default function Settings() {
  const s = useSettings()
  const [status, setStatus] = useState<string>('')
  const [models, setModels] = useState<string[]>([])
  const [fields, setFields] = useState<string[]>([])
  const [decks, setDecks] = useState<string[]>([])
  const [draft, setDraft] = useState({ name: '', query: '', model: '', sentence: '', audio: '', translation: '', source: '', url: '' })

  async function connect() {
    try {
      const p = await anki(s.ankiUrl).requestPermission()
      if (p.permission !== 'granted') { setStatus('AnkiConnect denied access. Add this origin to webCorsOriginList in the add-on config.'); return }
      setModels(await anki(s.ankiUrl).modelNames()); setDecks(await anki(s.ankiUrl).deckNames()); setStatus('Connected')
    } catch (e) { setStatus(`Cannot reach AnkiConnect at ${s.ankiUrl}: ${(e as Error).message}`) }
  }
  useEffect(() => { if (draft.model) anki(s.ankiUrl).modelFieldNames(draft.model).then(setFields).catch(() => setFields([])) }, [draft.model, s.ankiUrl])

  const sel = (label: string, value: string, onChange: (v: string) => void, opts: string[], allowEmpty = false) => (
    <label className="flex flex-col gap-1 text-sm text-fgdim">{label}
      <select className="bg-panel2 border border-line rounded px-2 py-1 text-fg" value={value} onChange={(e) => onChange(e.target.value)}>
        {allowEmpty && <option value="">—</option>}{opts.map((o) => <option key={o}>{o}</option>)}
      </select></label>)

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-8">
      <h1 className="text-xl text-fghi">Settings</h1>
      <section className="space-y-3">
        <h2 className="text-fghi">Anki</h2>
        <div className="flex gap-2 items-end">
          <label className="flex-1 text-sm text-fgdim">AnkiConnect URL
            <input className="w-full bg-panel2 border border-line rounded px-2 py-1 text-fg" value={s.ankiUrl} onChange={(e) => s.set({ ankiUrl: e.target.value })} /></label>
          <button className="btn" onClick={connect}>Connect</button>
        </div>
        <p className="text-sm text-fgdim">{status}</p>
        <h3 className="text-fg">Import queries</h3>
        <ul className="text-sm">{s.importQueries.map((q) => (
          <li key={q.name} className="flex justify-between border-b border-line py-1"><span>{q.name} · <code>{q.query}</code></span><button className="text-bad" onClick={() => s.removeQuery(q.name)}>remove</button></li>))}</ul>
        <div className="grid grid-cols-2 gap-3 bg-panel border border-line rounded p-3">
          <input className="inp" placeholder="Name (e.g. Mining)" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          <input className="inp" placeholder="Query (e.g. deck:Mining tag:asbplayer)" value={draft.query} onChange={(e) => setDraft({ ...draft, query: e.target.value })} />
          {sel('Note type', draft.model, (v) => setDraft({ ...draft, model: v }), models, true)}
          {sel('Sentence field', draft.sentence, (v) => setDraft({ ...draft, sentence: v }), fields, true)}
          {sel('Audio field', draft.audio, (v) => setDraft({ ...draft, audio: v }), fields, true)}
          {sel('Translation field', draft.translation, (v) => setDraft({ ...draft, translation: v }), fields, true)}
          {sel('Source field', draft.source, (v) => setDraft({ ...draft, source: v }), fields, true)}
          {sel('URL field', draft.url, (v) => setDraft({ ...draft, url: v }), fields, true)}
          <button className="btn col-span-2" disabled={!draft.name || !draft.query || !draft.sentence || !draft.audio}
            onClick={() => { s.addQuery({ name: draft.name, query: draft.query, mapping: { sentence: draft.sentence, audio: draft.audio, translation: draft.translation || undefined, source: draft.source || undefined, url: draft.url || undefined } }); setDraft({ ...draft, name: '', query: '' }) }}>Add query</button>
        </div>
        <h3 className="text-fg">Export note type</h3>
        <div className="grid grid-cols-2 gap-3 bg-panel border border-line rounded p-3">
          {sel('Deck', s.exportNote?.deckName ?? '', (v) => s.set({ exportNote: { deckName: v, modelName: s.exportNote?.modelName ?? '', fields: s.exportNote?.fields ?? { sentence: '', audio: '' } } }), decks, true)}
          {sel('Note type', s.exportNote?.modelName ?? '', (v) => { setDraft({ ...draft, model: v }); s.set({ exportNote: { deckName: s.exportNote?.deckName ?? '', modelName: v, fields: s.exportNote?.fields ?? { sentence: '', audio: '' } } }) }, models, true)}
          {(['sentence', 'pinyin', 'translation', 'audio'] as const).map((k) =>
            sel(`${k} field`, s.exportNote?.fields[k] ?? '', (v) => s.set({ exportNote: { ...s.exportNote!, fields: { ...s.exportNote!.fields, [k]: v } } }), fields, true))}
        </div>
      </section>
      <section className="space-y-2">
        <h2 className="text-fghi">Practice</h2>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={s.practice.hideTextWhileRecording} onChange={(e) => s.set({ practice: { ...s.practice, hideTextWhileRecording: e.target.checked } })} /> Hide text while recording</label>
        {([['chorusPasses', 'Chorus passes'], ['flowGapFactor', 'Flow gap factor'], ['moveOnAfter', 'Move-on hint after N attempts'], ['defaultRate', 'Default speed']] as const).map(([k, label]) => (
          <label key={k} className="flex items-center gap-2 text-sm">{label}
            <input type="number" step="0.05" className="inp w-24" value={s.practice[k]} onChange={(e) => s.set({ practice: { ...s.practice, [k]: Number(e.target.value) } })} /></label>))}
        <label className="flex items-center gap-2 text-sm">Language parent (speaker name)
          <input className="inp" value={s.languageParent ?? ''} onChange={(e) => s.set({ languageParent: e.target.value || null })} /></label>
      </section>
    </div>
  )
}
```

Add to `index.css`: `.btn { @apply px-3 py-1 rounded border border-accent bg-[#1c2a3a] text-[#dce9f7] text-sm disabled:opacity-40; } .inp { @apply bg-panel2 border border-line rounded px-2 py-1 text-fg text-sm; }`

Add route `/settings` in `App.tsx`.

- [ ] **Step 5: Run tests**

Run: `cd frontend && npx vitest run`
Expected: all pass

- [ ] **Step 6: Commit**

```bash
git add frontend && git commit -m "feat(frontend): persisted settings store and settings page"
```

---

### Task 4: Library page with upload, job progress and Anki import

**Files:**
- Create: `frontend/src/lib/library.ts`, `frontend/src/lib/library.test.ts`, `frontend/src/pages/Library.tsx`, `frontend/src/components/Shell.tsx`, `frontend/src/anki/runImport.ts`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- `lib/library.ts`: `groupBySpeaker(lessons, languageParent) -> { speaker: string; lessons: Lesson[]; pinned: boolean }[]` (pinned first, then by most recent lesson; Anki lessons grouped under their speaker like any other).
- `anki/runImport.ts`: `runAnkiImport(q: ImportQuery, ankiUrl, onProgress: (msg: string) => void) -> Promise<{ jobs: {job_id; lesson_id; title}[]; skipped: number }>` — findNotes → notesInfo in batches of 50 → payload → `api.lessons.ankiImport`.
- `components/Shell.tsx`: header with tabs Library · Review · Stats · Settings; children below.

- [ ] **Step 1: Failing test**

`frontend/src/lib/library.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { groupBySpeaker } from './library'
import type { Lesson } from '../api/types'

const L = (id: number, speaker: string, created: string): Lesson => ({ id, title: `t${id}`, speaker, source_type: 'upload', source_ref: '', duration_s: 0, created_at: created, status: 'ready', error: null, segment_count: 1, practised_count: 0, mean_last_score: null })

describe('groupBySpeaker', () => {
  it('pins the language parent and orders groups by recency', () => {
    const g = groupBySpeaker([L(1, 'A', '2026-01-01'), L(2, 'B', '2026-03-01'), L(3, 'A', '2026-02-01')], 'B')
    expect(g.map((x) => x.speaker)).toEqual(['B', 'A'])
    expect(g[0].pinned).toBe(true)
    expect(g[1].lessons.map((l) => l.id)).toEqual([3, 1])
  })
  it('groups empty speaker as Unsorted', () => {
    expect(groupBySpeaker([L(1, '', '2026-01-01')], null)[0].speaker).toBe('Unsorted')
  })
})
```

- [ ] **Step 2: Run to verify fail**

Run: `cd frontend && npx vitest run src/lib/library.test.ts`
Expected: FAIL

- [ ] **Step 3: Implement**

`frontend/src/lib/library.ts`:
```ts
import type { Lesson } from '../api/types'

export function groupBySpeaker(lessons: Lesson[], languageParent: string | null) {
  const map = new Map<string, Lesson[]>()
  for (const l of lessons) {
    const k = l.speaker?.trim() || 'Unsorted'
    map.set(k, [...(map.get(k) ?? []), l])
  }
  const groups = [...map.entries()].map(([speaker, ls]) => ({
    speaker, pinned: !!languageParent && speaker === languageParent,
    lessons: [...ls].sort((a, b) => b.created_at.localeCompare(a.created_at)),
  }))
  return groups.sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.lessons[0].created_at.localeCompare(a.lessons[0].created_at))
}
```

`frontend/src/anki/runImport.ts`:
```ts
import { anki } from './client'
import { notesToImportPayload } from './import'
import { api } from '../api/client'
import type { ImportQuery } from '../store/settings'

export async function runAnkiImport(q: ImportQuery, ankiUrl: string, onProgress: (msg: string) => void) {
  const a = anki(ankiUrl)
  const ids = await a.findNotes(q.query)
  onProgress(`${ids.length} notes match`)
  const notes = []
  for (let i = 0; i < ids.length; i += 50) notes.push(...(await a.notesInfo(ids.slice(i, i + 50))))
  let done = 0
  const { payload, skipped } = await notesToImportPayload(notes, q.mapping, async (name) => {
    const r = await a.retrieveMediaFile(name); done++
    if (done % 10 === 0) onProgress(`fetched ${done}/${notes.length} clips`)
    return r
  })
  if (!payload.length) return { jobs: [], skipped }
  const res = await api.lessons.ankiImport(q.name, payload)
  return { jobs: res.jobs, skipped }
}
```

`frontend/src/components/Shell.tsx`:
```tsx
import { NavLink } from 'react-router-dom'
export default function Shell({ children }: { children: React.ReactNode }) {
  const tab = 'px-3 py-1 rounded border border-line text-sm'
  return (
    <div className="min-h-full">
      <header className="flex items-center justify-between px-6 py-3 border-b border-line">
        <span className="text-fghi">shadow</span>
        <nav className="flex gap-2">
          {[['/library', 'Library'], ['/review', 'Review'], ['/stats', 'Stats'], ['/settings', 'Settings']].map(([to, label]) => (
            <NavLink key={to} to={to} className={({ isActive }) => `${tab} ${isActive ? 'bg-[#1c2a3a] border-accent text-white' : 'text-fgdim'}`}>{label}</NavLink>))}
        </nav>
      </header>
      {children}
    </div>
  )
}
```

`frontend/src/pages/Library.tsx`:
```tsx
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { Job, Lesson } from '../api/types'
import { groupBySpeaker } from '../lib/library'
import { useSettings } from '../store/settings'
import { runAnkiImport } from '../anki/runImport'
import Shell from '../components/Shell'

export default function Library() {
  const [lessons, setLessons] = useState<Lesson[]>([])
  const [jobs, setJobs] = useState<Record<number, Job>>({})
  const [msg, setMsg] = useState('')
  const { languageParent, importQueries, ankiUrl } = useSettings()
  const reload = useCallback(() => api.lessons.list().then(setLessons).catch((e) => setMsg(String(e))), [])
  useEffect(() => { reload() }, [reload])

  function watch(job_id: string, lesson_id: number) {
    api.jobs.events(job_id, (j) => { setJobs((m) => ({ ...m, [lesson_id]: j })); if (j.status === 'done' || j.status === 'error') reload() })
  }
  async function onFiles(files: FileList | null) {
    if (!files?.length) return
    const list = [...files]
    const media = list.find((f) => !/\.(srt|vtt|txt)$/i.test(f.name))
    const subs = list.find((f) => /\.(srt|vtt|txt)$/i.test(f.name))
    if (!media) { setMsg('Drop an audio or video file (optionally with an .srt).'); return }
    const speaker = window.prompt('Speaker / channel name?', '') ?? ''
    const r = await api.lessons.upload(media, { subtitles: subs, speaker })
    await reload(); watch(r.job_id, r.lesson_id)
  }
  async function importQuery(name: string) {
    const q = importQueries.find((x) => x.name === name)!
    try {
      const { jobs: js, skipped } = await runAnkiImport(q, ankiUrl, setMsg)
      setMsg(`${js.length} lesson(s) updating, ${skipped} note(s) skipped`)
      await reload(); js.forEach((j) => watch(j.job_id, j.lesson_id))
    } catch (e) { setMsg(`Anki import failed: ${(e as Error).message}`) }
  }

  const groups = groupBySpeaker(lessons, languageParent)
  return (
    <Shell>
      <div className="max-w-6xl mx-auto p-6 space-y-6">
        <div className="flex gap-3 items-center border border-dashed border-line rounded p-4"
          onDragOver={(e) => e.preventDefault()} onDrop={(e) => { e.preventDefault(); onFiles(e.dataTransfer.files) }}>
          <label className="flex-1 text-fgdim text-sm cursor-pointer">Drop audio/video (+ .srt) here, or click to choose
            <input type="file" multiple className="hidden" onChange={(e) => onFiles(e.target.files)} /></label>
          {importQueries.map((q) => <button key={q.name} className="btn" onClick={() => importQuery(q.name)}>⟳ Anki · {q.name}</button>)}
          {!importQueries.length && <Link to="/settings" className="btn">Set up Anki import</Link>}
        </div>
        {msg && <p className="text-sm text-fgdim">{msg}</p>}
        {groups.map((g) => (
          <section key={g.speaker}>
            <h2 className="text-xs uppercase tracking-widest text-fgdim mb-2 flex justify-between">
              <span>{g.pinned && '★ '}{g.speaker} · {g.lessons.length} lesson{g.lessons.length > 1 ? 's' : ''}</span></h2>
            <div className="grid grid-cols-3 gap-3">
              {g.lessons.map((l) => {
                const j = jobs[l.id]; const busy = l.status !== 'ready' && l.status !== 'error'
                const frac = busy ? (j?.fraction ?? 0) : (l.segment_count ? l.practised_count / l.segment_count : 0)
                return (
                  <Link key={l.id} to={l.status === 'ready' ? `/practice/${l.id}` : '#'} className="bg-panel border border-line rounded p-3 block hover:border-accent">
                    <div className="font-hanzi text-fghi truncate">{l.title}{l.source_type === 'anki' && <span className="ml-2 text-[10px] px-1 rounded bg-[#2b1f3a] text-[#d6c3f0]">anki</span>}</div>
                    <div className="text-xs text-fgdim mt-1">
                      {l.status === 'error' ? <span className="text-bad">error: {l.error}</span>
                        : busy ? `${j?.stage ?? l.status}… ${Math.round(frac * 100)} %`
                        : `${l.segment_count} sentences · ${l.practised_count} practised${l.mean_last_score != null ? ` · mean ${Math.round(l.mean_last_score * 100)}` : ''}`}
                    </div>
                    <div className="h-1 bg-panel2 rounded mt-2 overflow-hidden"><div className={`h-full ${busy ? 'bg-accent' : 'bg-ok'}`} style={{ width: `${frac * 100}%` }} /></div>
                  </Link>)
              })}
            </div>
          </section>))}
      </div>
    </Shell>
  )
}
```

Add route `/library` and a placeholder `/practice/:id` (filled in Task 9) to `App.tsx`.

- [ ] **Step 4: Run tests, start dev servers, upload a real file**

Run: `cd frontend && npx vitest run` → pass. Then `make dev`, open `http://localhost:5173/library`, drop a short `.wav` or `.mp4`. Expected: tile appears with a live stage bar, then `N sentences`.

- [ ] **Step 5: Commit**

```bash
git add frontend && git commit -m "feat(frontend): library with upload, job progress and Anki import"
```

---

### Task 5: Yomitan-compatible sentence component

**Files:**
- Create: `frontend/src/components/Sentence.tsx`, `frontend/src/components/Sentence.test.tsx`, `frontend/src/lib/sentence.ts`, `frontend/src/lib/sentence.test.ts`

**Interfaces:**
- `lib/sentence.ts`: `sentenceRuns(text, words) -> { text: string; pinyin?: string }[]` — covers every character of `text` in order: word runs carry pinyin; punctuation and uncovered gaps become runs without pinyin; `fontSizeClass(len) -> string`.
- `<Sentence text words showPinyin showHanzi translation showTranslation />` renders `<p lang="zh" class="sentence [hide-pinyin]">` with `<ruby>` per word run and plain text for others; when `showHanzi` is false renders `<p class="sentence placeholder">…</p>`.

- [ ] **Step 1: Failing tests**

`frontend/src/lib/sentence.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { sentenceRuns, fontSizeClass } from './sentence'

const words = [
  { word: '我', pinyin: 'wǒ', tones: [3], char_from: 0, char_to: 0, syllables: [] },
  { word: '今天', pinyin: 'jīntiān', tones: [1, 1], char_from: 1, char_to: 2, syllables: [] },
]
describe('sentenceRuns', () => {
  it('covers text with word runs and bare punctuation', () => {
    expect(sentenceRuns('我今天。', words)).toEqual([{ text: '我', pinyin: 'wǒ' }, { text: '今天', pinyin: 'jīntiān' }, { text: '。' }])
  })
  it('falls back to one bare run without words', () => {
    expect(sentenceRuns('你好。', null)).toEqual([{ text: '你好。' }])
  })
  it('fills gaps when words do not cover text', () => {
    expect(sentenceRuns('我今天呢', words)).toEqual([{ text: '我', pinyin: 'wǒ' }, { text: '今天', pinyin: 'jīntiān' }, { text: '呢' }])
  })
})
describe('fontSizeClass', () => {
  it('steps down with length', () => {
    expect(fontSizeClass(8)).toBe('text-[40px]'); expect(fontSizeClass(18)).toBe('text-[32px]')
    expect(fontSizeClass(25)).toBe('text-[28px]'); expect(fontSizeClass(40)).toBe('text-[24px]')
  })
})
```

`frontend/src/components/Sentence.test.tsx`:
```tsx
import { render } from '@testing-library/react'
import { describe, it, expect } from 'vitest'
import Sentence from './Sentence'

const words = [{ word: '今天', pinyin: 'jīntiān', tones: [1, 1], char_from: 0, char_to: 1, syllables: [] }]

describe('<Sentence>', () => {
  it('renders one ruby per word with rt pinyin and contiguous text', () => {
    const { container } = render(<Sentence text="今天。" words={words} showPinyin showHanzi />)
    const p = container.querySelector('p.sentence')!
    expect(p.getAttribute('lang')).toBe('zh')
    expect(p.querySelectorAll('ruby').length).toBe(1)
    expect(p.querySelector('rt')!.textContent).toBe('jīntiān')
    expect(p.querySelectorAll('span').length).toBe(0)
    const visible = [...p.childNodes].map((n) => (n.nodeName === 'RUBY' ? n.firstChild!.textContent : n.textContent)).join('')
    expect(visible).toBe('今天。')
  })
  it('hides pinyin via class only', () => {
    const { container } = render(<Sentence text="今天" words={words} showPinyin={false} showHanzi />)
    expect(container.querySelector('p.sentence')!.classList.contains('hide-pinyin')).toBe(true)
    expect(container.querySelector('rt')).not.toBeNull()
  })
  it('survives missing words', () => {
    const { container } = render(<Sentence text="你好。" words={null} showPinyin showHanzi />)
    expect(container.querySelector('p.sentence')!.textContent).toBe('你好。')
  })
})
```

- [ ] **Step 2: Run to verify fail**

Run: `cd frontend && npx vitest run src/lib/sentence.test.ts src/components/Sentence.test.tsx`
Expected: FAIL

- [ ] **Step 3: Implement**

`frontend/src/lib/sentence.ts`:
```ts
import type { Word } from '../api/types'

export interface Run { text: string; pinyin?: string }

export function sentenceRuns(text: string, words: Word[] | null | undefined): Run[] {
  if (!words?.length) return [{ text }]
  const runs: Run[] = []
  let pos = 0
  const flushGap = (to: number) => { if (to > pos) runs.push({ text: text.slice(pos, to) }) }
  for (const w of [...words].sort((a, b) => a.char_from - b.char_from)) {
    if (w.char_from < pos) continue
    flushGap(w.char_from)
    runs.push({ text: text.slice(w.char_from, w.char_to + 1), pinyin: w.pinyin })
    pos = w.char_to + 1
  }
  flushGap(text.length)
  return runs
}

export function fontSizeClass(len: number): string {
  if (len <= 10) return 'text-[40px]'
  if (len <= 18) return 'text-[32px]'
  if (len <= 25) return 'text-[28px]'
  return 'text-[24px]'
}
```

`frontend/src/components/Sentence.tsx`:
```tsx
import type { Word } from '../api/types'
import { fontSizeClass, sentenceRuns } from '../lib/sentence'

interface Props { text: string; words: Word[] | null | undefined; showPinyin: boolean; showHanzi: boolean; translation?: string | null; showTranslation?: boolean }

export default function Sentence({ text, words, showPinyin, showHanzi, translation, showTranslation }: Props) {
  if (!showHanzi) {
    return <div className="text-center"><p className="sentence text-fgdim text-[28px] select-none">· · ·</p>{showTranslation && translation && <p className="text-fgdim italic text-sm mt-1">{translation}</p>}</div>
  }
  return (
    <div className="text-center">
      <p lang="zh" className={`sentence ${fontSizeClass(text.length)} ${showPinyin ? '' : 'hide-pinyin'}`}>
        {sentenceRuns(text, words).map((r, i) => (r.pinyin ? <ruby key={i}>{r.text}<rt>{r.pinyin}</rt></ruby> : r.text))}
      </p>
      {showTranslation && translation && <p className="text-fgdim italic text-sm mt-1">{translation}</p>}
    </div>
  )
}
```

Note: React renders adjacent string children as separate text nodes, each still a plain DOM text node directly under `<p>`, which Yomitan scans across. Do not wrap them in spans.

- [ ] **Step 4: Run tests**

Run: `cd frontend && npx vitest run`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add frontend && git commit -m "feat(frontend): Yomitan-compatible sentence rendering"
```

---

### Task 6: Clip player

**Files:**
- Create: `frontend/src/audio/player.ts`, `frontend/src/audio/player.test.ts`

**Interfaces:**
- `class ClipPlayer { constructor(); preload(url: string): Promise<void>; play(url: string, rate: number, onTime?: (t: number) => void): Promise<void> (resolves on ended); stop(): void; get currentTime(): number; peaksFor(url, buckets): Promise<Float32Array> }` — one hidden `<audio>` element per URL cached in a Map, `preservesPitch = true`, `playbackRate = rate`; `peaksFor` decodes via `AudioContext.decodeAudioData` from a fetched ArrayBuffer and returns `peaks(samples, buckets)`.
- `peaks(samples: Float32Array, buckets: number) -> Float32Array` (max |x| per bucket, pure).
- `playSequence(player, items: { url: string; rate: number }[], gapMs = 250): Promise<void>`.

- [ ] **Step 1: Failing test (pure parts)**

`frontend/src/audio/player.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { peaks } from './player'

describe('peaks', () => {
  it('returns max abs per bucket', () => {
    const s = new Float32Array([0.1, -0.5, 0.2, 0.9, 0.0, -0.3])
    expect([...peaks(s, 3)]).toEqual([0.5, 0.9, 0.3])
  })
  it('handles fewer samples than buckets', () => {
    expect(peaks(new Float32Array([0.4]), 4).length).toBe(4)
  })
})
```

- [ ] **Step 2: Run to verify fail** → `cd frontend && npx vitest run src/audio/player.test.ts` → FAIL

- [ ] **Step 3: Implement**

`frontend/src/audio/player.ts`:
```ts
export function peaks(samples: Float32Array, buckets: number): Float32Array {
  const out = new Float32Array(buckets)
  const per = samples.length / buckets
  for (let b = 0; b < buckets; b++) {
    const a = Math.floor(b * per), z = Math.max(a + 1, Math.floor((b + 1) * per))
    let m = 0
    for (let i = a; i < z && i < samples.length; i++) m = Math.max(m, Math.abs(samples[i]))
    out[b] = m
  }
  return out
}

export class ClipPlayer {
  private els = new Map<string, HTMLAudioElement>()
  private current: HTMLAudioElement | null = null
  private ctx: AudioContext | null = null
  private peakCache = new Map<string, Float32Array>()

  private el(url: string): HTMLAudioElement {
    let a = this.els.get(url)
    if (!a) { a = new Audio(url); a.preload = 'auto'; (a as any).preservesPitch = true; this.els.set(url, a) }
    return a
  }
  async preload(url: string) { const a = this.el(url); if (a.readyState < 2) await new Promise<void>((r) => { a.oncanplaythrough = () => r(); a.onerror = () => r(); a.load() }) }
  get currentTime() { return this.current?.currentTime ?? 0 }
  stop() { if (this.current) { this.current.pause(); this.current.currentTime = 0; this.current = null } }
  play(url: string, rate: number, onTime?: (t: number) => void): Promise<void> {
    this.stop()
    const a = this.el(url); this.current = a; a.playbackRate = rate; a.currentTime = 0
    return new Promise((resolve, reject) => {
      let raf = 0
      const tick = () => { onTime?.(a.currentTime); raf = requestAnimationFrame(tick) }
      a.onended = () => { cancelAnimationFrame(raf); onTime?.(a.duration); if (this.current === a) this.current = null; resolve() }
      a.onerror = () => { cancelAnimationFrame(raf); reject(new Error('audio error')) }
      a.play().then(() => { if (onTime) raf = requestAnimationFrame(tick) }).catch(reject)
    })
  }
  async peaksFor(url: string, buckets: number): Promise<Float32Array> {
    const key = `${url}#${buckets}`
    const hit = this.peakCache.get(key); if (hit) return hit
    this.ctx ??= new AudioContext()
    const buf = await this.ctx.decodeAudioData(await (await fetch(url)).arrayBuffer())
    const p = peaks(buf.getChannelData(0), buckets); this.peakCache.set(key, p); return p
  }
}

export async function playSequence(player: ClipPlayer, items: { url: string; rate: number; onTime?: (t: number) => void }[], gapMs = 250) {
  for (const it of items) { await player.play(it.url, it.rate, it.onTime); await new Promise((r) => setTimeout(r, gapMs)) }
}
```

- [ ] **Step 4: Run tests** → pass. **Step 5: Commit** `git commit -am "feat(frontend): clip player with pitch-preserving rate and peaks"` (after `git add`).

---

### Task 7: Recorder — AudioWorklet capture, WAV encoding, VAD

**Files:**
- Create: `frontend/public/worklets/pcm-capture.js`, `frontend/src/audio/pcm.ts`, `frontend/src/audio/recorder.ts`, `frontend/src/audio/pcm.test.ts`

**Interfaces:**
- `pcm.ts` (pure): `concat(chunks: Float32Array[]) -> Float32Array`; `downsample(x, fromSr, toSr=16000) -> Float32Array` (box-filter average); `encodeWav16(x, sr) -> Blob` (44-byte RIFF header, PCM16 mono); `rms(x) -> number`; `findSilenceEnd(x, sr, opts = { threshold: 0.01, holdMs: 1200, minSpeechMs: 300 }) -> number | null` (sample index where speech has ended and `holdMs` of silence followed; `null` if not yet).
- `recorder.ts`: `class Recorder { constructor(ctx: AudioContext); start(): Promise<void>; stop(): Float32Array; get sampleRate(); get startTime() /* ctx.currentTime when first chunk arrived */; snapshot(): Float32Array /* current samples without stopping */; slice(t0: number, t1: number): Float32Array /* ctx-time absolute */ }`; `toWav16k(samples, sr) -> Blob`.

- [ ] **Step 1: Failing tests**

`frontend/src/audio/pcm.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { concat, downsample, encodeWav16, findSilenceEnd, rms } from './pcm'

describe('pcm', () => {
  it('concat', () => { expect([...concat([new Float32Array([1, 2]), new Float32Array([3])])]).toEqual([1, 2, 3]) })
  it('downsample 48k→16k averages triples', () => {
    const x = new Float32Array([0.3, 0.3, 0.3, 0.6, 0.6, 0.6])
    const y = downsample(x, 48000, 16000)
    expect(y.length).toBe(2); expect(y[0]).toBeCloseTo(0.3); expect(y[1]).toBeCloseTo(0.6)
  })
  it('encodeWav16 writes a valid header', async () => {
    const blob = encodeWav16(new Float32Array([0, 0.5, -0.5]), 16000)
    const dv = new DataView(await blob.arrayBuffer())
    expect(String.fromCharCode(dv.getUint8(0), dv.getUint8(1), dv.getUint8(2), dv.getUint8(3))).toBe('RIFF')
    expect(dv.getUint32(24, true)).toBe(16000); expect(dv.getUint16(22, true)).toBe(1); expect(dv.getUint16(34, true)).toBe(16)
    expect(dv.getUint32(40, true)).toBe(6); expect(dv.getInt16(46, true)).toBe(16383)
  })
  it('findSilenceEnd detects speech then 1.2 s of silence', () => {
    const sr = 16000
    const speech = Float32Array.from({ length: sr }, (_, i) => 0.2 * Math.sin(i / 10))
    const silence = new Float32Array(sr * 1.5)
    const x = concat([new Float32Array(sr * 0.5), speech, silence])
    const idx = findSilenceEnd(x, sr)
    expect(idx).not.toBeNull(); expect(idx!).toBeGreaterThan(sr * 1.5); expect(idx!).toBeLessThan(sr * 2.9)
    expect(findSilenceEnd(concat([new Float32Array(sr * 0.5), speech]), sr)).toBeNull()
    expect(findSilenceEnd(new Float32Array(sr * 3), sr)).toBeNull()      // never spoke
    expect(rms(new Float32Array([0.5, -0.5]))).toBeCloseTo(0.5)
  })
})
```

- [ ] **Step 2: Run to verify fail** → FAIL

- [ ] **Step 3: Implement**

`frontend/public/worklets/pcm-capture.js`:
```js
class PcmCapture extends AudioWorkletProcessor {
  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (ch) this.port.postMessage(ch.slice(0))
    return true
  }
}
registerProcessor('pcm-capture', PcmCapture)
```

`frontend/src/audio/pcm.ts`:
```ts
export function concat(chunks: Float32Array[]): Float32Array {
  const out = new Float32Array(chunks.reduce((n, c) => n + c.length, 0))
  let o = 0
  for (const c of chunks) { out.set(c, o); o += c.length }
  return out
}

export function downsample(x: Float32Array, fromSr: number, toSr = 16000): Float32Array {
  if (fromSr === toSr) return x
  const ratio = fromSr / toSr
  const n = Math.floor(x.length / ratio)
  const out = new Float32Array(n)
  for (let i = 0; i < n; i++) {
    const a = Math.floor(i * ratio), z = Math.min(x.length, Math.floor((i + 1) * ratio))
    let s = 0
    for (let j = a; j < z; j++) s += x[j]
    out[i] = s / Math.max(1, z - a)
  }
  return out
}

export function encodeWav16(x: Float32Array, sr: number): Blob {
  const buf = new ArrayBuffer(44 + x.length * 2)
  const dv = new DataView(buf)
  const str = (o: number, s: string) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)) }
  str(0, 'RIFF'); dv.setUint32(4, 36 + x.length * 2, true); str(8, 'WAVE'); str(12, 'fmt ')
  dv.setUint32(16, 16, true); dv.setUint16(20, 1, true); dv.setUint16(22, 1, true); dv.setUint32(24, sr, true)
  dv.setUint32(28, sr * 2, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true); str(36, 'data'); dv.setUint32(40, x.length * 2, true)
  for (let i = 0; i < x.length; i++) { const v = Math.max(-1, Math.min(1, x[i])); dv.setInt16(44 + i * 2, v < 0 ? v * 0x8000 : v * 0x7fff, true) }
  return new Blob([buf], { type: 'audio/wav' })
}

export function rms(x: Float32Array): number {
  let s = 0
  for (let i = 0; i < x.length; i++) s += x[i] * x[i]
  return Math.sqrt(s / Math.max(1, x.length))
}

export interface VadOpts { threshold: number; holdMs: number; minSpeechMs: number }
export function findSilenceEnd(x: Float32Array, sr: number, opts: VadOpts = { threshold: 0.01, holdMs: 1200, minSpeechMs: 300 }): number | null {
  const frame = Math.floor(sr * 0.02)
  let speechFrames = 0, silentFrames = 0, spoke = false, lastSpeechEnd = -1
  const needSpeech = Math.ceil(opts.minSpeechMs / 20), needSilence = Math.ceil(opts.holdMs / 20)
  for (let a = 0; a + frame <= x.length; a += frame) {
    if (rms(x.subarray(a, a + frame)) > opts.threshold) { speechFrames++; silentFrames = 0; if (speechFrames >= needSpeech) { spoke = true; lastSpeechEnd = a + frame } }
    else { silentFrames++; if (spoke && silentFrames >= needSilence) return lastSpeechEnd }
  }
  return null
}
```

`frontend/src/audio/recorder.ts`:
```ts
import { concat, downsample, encodeWav16 } from './pcm'

export class Recorder {
  private chunks: Float32Array[] = []
  private node: AudioWorkletNode | null = null
  private src: MediaStreamAudioSourceNode | null = null
  private stream: MediaStream | null = null
  private _start = 0
  private loaded = false
  constructor(private ctx: AudioContext) {}
  get sampleRate() { return this.ctx.sampleRate }
  get startTime() { return this._start }

  async start() {
    if (this.ctx.state === 'suspended') await this.ctx.resume()
    if (!this.loaded) { await this.ctx.audioWorklet.addModule('/worklets/pcm-capture.js'); this.loaded = true }
    this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: false, noiseSuppression: false, autoGainControl: false } })
    this.src = this.ctx.createMediaStreamSource(this.stream)
    this.node = new AudioWorkletNode(this.ctx, 'pcm-capture')
    this.chunks = []
    this._start = 0
    this.node.port.onmessage = (e) => { if (!this._start) this._start = this.ctx.currentTime - (e.data as Float32Array).length / this.ctx.sampleRate; this.chunks.push(e.data as Float32Array) }
    this.src.connect(this.node)
  }
  snapshot(): Float32Array { return concat(this.chunks) }
  stop(): Float32Array {
    this.src?.disconnect(); this.node?.disconnect(); this.stream?.getTracks().forEach((t) => t.stop())
    this.src = this.node = this.stream = null
    return this.snapshot()
  }
  slice(t0: number, t1: number): Float32Array {
    const all = this.snapshot()
    const a = Math.max(0, Math.floor((t0 - this._start) * this.ctx.sampleRate))
    const z = Math.min(all.length, Math.floor((t1 - this._start) * this.ctx.sampleRate))
    return all.slice(a, Math.max(a, z))
  }
}

export const toWav16k = (samples: Float32Array, sr: number) => encodeWav16(downsample(samples, sr, 16000), 16000)
```

- [ ] **Step 4: Run tests** → pass. **Step 5: Commit** `feat(frontend): AudioWorklet recorder, WAV16k encoder, RMS VAD`.

---

### Task 8: Two-track feedback block (unscored state)

**Files:**
- Create: `frontend/src/lib/cells.ts`, `frontend/src/lib/cells.test.ts`, `frontend/src/components/Waveform.tsx`, `frontend/src/components/CellRow.tsx`, `frontend/src/components/TwoTrack.tsx`

**Interfaces:**
- `lib/cells.ts`: `Cell { ch: string; pinyin: string; tone: number; score?: number | null; status?: 'ok'|'suspect'|'missing'|'unvoiced'|'neutral' }`; `cellsFromWords(words: Word[] | null, text: string) -> Cell[]` (one per speech character, tone from syllables, `status:'neutral'`); `cellClass(cell) -> string`; `cellStatusFromScore(score: number | null | undefined) -> status`.
- `<Waveform peaks duration ticks playhead color height />` canvas drawing bars, tick marks at `ticks` (seconds), playhead line.
- `<CellRow cells variant='ref'|'you' onCellClick(i) />`.
- `<TwoTrack segment refPeaks refDuration youPeaks youDuration refPlayhead youPlayhead onPlayRef onPlayYou onLoopSyllable scoreHeader />` — shared time scale: `pxPerSec = width / max(refDuration, youDuration)`.

- [ ] **Step 1: Failing test**

`frontend/src/lib/cells.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { cellsFromWords, cellClass, cellStatusFromScore } from './cells'

const words = [{ word: '你好', pinyin: 'nǐhǎo', tones: [2, 3], char_from: 0, char_to: 1, syllables: [
  { ch: '你', pinyin: 'ní', pinyin_toneless: 'ni', tone: 2 }, { ch: '好', pinyin: 'hǎo', pinyin_toneless: 'hao', tone: 3 }] }]

describe('cells', () => {
  it('one cell per speech character with tone', () => {
    const c = cellsFromWords(words, '你好。')
    expect(c.map((x) => [x.ch, x.tone])).toEqual([['你', 2], ['好', 3]])
    expect(c[0].status).toBe('neutral')
  })
  it('falls back to text chars without words', () => {
    expect(cellsFromWords(null, '好吗？').map((x) => x.ch)).toEqual(['好', '吗'])
  })
  it('classes by status and score thresholds', () => {
    expect(cellClass({ ch: 'x', pinyin: '', tone: 1, status: 'ok' })).toBe('cell-ok')
    expect(cellStatusFromScore(0.85)).toBe('ok'); expect(cellStatusFromScore(0.5)).toBe('suspect'); expect(cellStatusFromScore(null)).toBe('neutral')
  })
})
```

- [ ] **Step 2: Run to verify fail** → FAIL

- [ ] **Step 3: Implement**

`frontend/src/lib/cells.ts`:
```ts
import type { Word } from '../api/types'
export type CellStatus = 'ok' | 'suspect' | 'missing' | 'unvoiced' | 'neutral'
export interface Cell { ch: string; pinyin: string; tone: number; score?: number | null; status?: CellStatus }
const PUNCT = /[\p{P}\p{S}\s]/u

export function cellsFromWords(words: Word[] | null | undefined, text: string): Cell[] {
  if (words?.length) return words.flatMap((w) => w.syllables.filter((s) => !PUNCT.test(s.ch)).map((s) => ({ ch: s.ch, pinyin: s.pinyin, tone: s.tone, status: 'neutral' as const })))
  return [...text].filter((c) => !PUNCT.test(c)).map((ch) => ({ ch, pinyin: '', tone: -1, status: 'neutral' as const }))
}
export function cellStatusFromScore(score: number | null | undefined): CellStatus {
  if (score == null) return 'neutral'
  return score >= 0.7 ? 'ok' : 'suspect'
}
export function cellClass(c: Cell): string {
  return { ok: 'cell-ok', suspect: 'cell-warn', missing: 'cell-bad', unvoiced: 'cell-unvoiced', neutral: 'cell-neutral' }[c.status ?? 'neutral']
}
```

`frontend/src/components/Waveform.tsx`:
```tsx
import { useEffect, useRef } from 'react'
interface Props { peaks: Float32Array | null; duration: number; pxPerSec: number; ticks?: number[]; playhead?: number | null; color: string; height?: number }
export default function Waveform({ peaks, duration, pxPerSec, ticks = [], playhead, color, height = 44 }: Props) {
  const ref = useRef<HTMLCanvasElement>(null)
  useEffect(() => {
    const c = ref.current; if (!c) return
    const w = Math.max(1, Math.round(duration * pxPerSec)); c.width = w; c.height = height
    const g = c.getContext('2d')!; g.clearRect(0, 0, w, height)
    if (peaks) { const bw = w / peaks.length; g.fillStyle = color; peaks.forEach((p, i) => { const h = Math.max(1, p * (height - 4)); g.fillRect(i * bw, (height - h) / 2, Math.max(1, bw - 1), h) }) }
    g.strokeStyle = '#3a434d'; ticks.forEach((t) => { const x = Math.round(t * pxPerSec) + 0.5; g.beginPath(); g.moveTo(x, 0); g.lineTo(x, height); g.stroke() })
    if (playhead != null) { const x = Math.round(playhead * pxPerSec) + 0.5; g.strokeStyle = '#f2f5f7'; g.beginPath(); g.moveTo(x, 0); g.lineTo(x, height); g.stroke() }
  }, [peaks, duration, pxPerSec, ticks, playhead, color, height])
  return <canvas ref={ref} style={{ width: Math.round(duration * pxPerSec), height }} />
}
```

`frontend/src/components/CellRow.tsx`:
```tsx
import { cellClass, type Cell } from '../lib/cells'
export default function CellRow({ cells, variant, onCellClick }: { cells: Cell[]; variant: 'ref' | 'you'; onCellClick?: (i: number) => void }) {
  return (
    <div className="flex flex-wrap gap-1 mt-2 justify-center">
      {cells.map((c, i) => (
        <button key={i} title={c.pinyin} onClick={() => onCellClick?.(i)}
          className={`w-10 max-w-[56px] rounded border px-1 py-1 text-center ${cellClass(c)}`}>
          <span className="block font-hanzi text-fghi text-sm leading-tight">{c.ch}</span>
          <span className="block text-[10px] text-ref">{variant === 'ref' ? `${c.pinyin} ${c.tone >= 0 ? c.tone : ''}` : `${c.tone >= 0 ? c.tone : ''}`}</span>
          {variant === 'you' && <span className="block text-[9px] text-fgdim">{c.score != null ? Math.round(c.score * 100) : c.status === 'unvoiced' ? '∅' : '–'}</span>}
        </button>))}
    </div>
  )
}
```

`frontend/src/components/TwoTrack.tsx`:
```tsx
import { useEffect, useRef, useState } from 'react'
import type { Segment } from '../api/types'
import { cellsFromWords } from '../lib/cells'
import CellRow from './CellRow'
import Waveform from './Waveform'

interface Props {
  segment: Segment
  refPeaks: Float32Array | null; refDuration: number; refPlayhead: number | null
  youPeaks: Float32Array | null; youDuration: number; youPlayhead: number | null
  onPlayRef: () => void; onPlayYou: () => void; onLoopSyllable: (i: number) => void
  scoreHeader?: React.ReactNode
}
export default function TwoTrack(p: Props) {
  const box = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(600)
  useEffect(() => { const ro = new ResizeObserver((e) => setWidth(e[0].contentRect.width)); if (box.current) ro.observe(box.current); return () => ro.disconnect() }, [])
  const longest = Math.max(p.refDuration, p.youDuration, 0.1)
  const pxPerSec = (width - 16) / longest
  const cells = cellsFromWords(p.segment.words_json, p.segment.text)
  const ticks = (p.segment.ref_alignment_json ?? []).map((s) => s.end - p.segment.start_s)
  const cap = 'flex justify-between text-[10px] uppercase tracking-widest text-fgdim mb-1'
  return (
    <div ref={box} className="space-y-2">
      <div className="bg-bg border border-line rounded p-2">
        <div className={cap}><span>Reference · {p.refDuration.toFixed(1)} s</span><button onClick={p.onPlayRef}>▶ Space</button></div>
        <Waveform peaks={p.refPeaks} duration={p.refDuration} pxPerSec={pxPerSec} ticks={ticks} playhead={p.refPlayhead} color="#2f4a66" />
        <CellRow cells={cells} variant="ref" onCellClick={p.onLoopSyllable} />
      </div>
      <div className="bg-bg border border-line rounded p-2">
        <div className={cap}><span>You{p.youDuration ? ` · ${p.youDuration.toFixed(1)} s · ${(p.youDuration / p.refDuration).toFixed(2)}×` : ''}</span>
          <span className="flex items-center gap-2">{p.scoreHeader ?? <span className="normal-case tracking-normal text-fgdim">score arrives in Phase 2</span>}<button onClick={p.onPlayYou} disabled={!p.youDuration}>▶ R</button></span></div>
        {p.youDuration ? <Waveform peaks={p.youPeaks} duration={p.youDuration} pxPerSec={pxPerSec} playhead={p.youPlayhead} color="#5a4a2a" /> : <div className="h-11 text-center text-fgdim text-sm leading-[44px]">record to compare</div>}
        <CellRow cells={cells} variant="you" />
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run tests** → pass. **Step 5: Commit** `feat(frontend): two-track feedback block with character cells`.

---

### Task 9: Practice page shell, keyboard map, Echo mode

**Files:**
- Create: `frontend/src/lib/echo.ts`, `frontend/src/lib/echo.test.ts`, `frontend/src/lib/keys.ts`, `frontend/src/lib/keys.test.ts`, `frontend/src/store/practice.ts`, `frontend/src/pages/Practice.tsx`, `frontend/src/components/Drawer.tsx` (list only; actions in Task 11), `frontend/src/components/Transport.tsx`, `frontend/src/components/TopBar.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- `lib/echo.ts`: `EchoState = 'idle' | 'playing' | 'recording' | 'uploading' | 'playback'`; `EchoEvent = 'PLAY' | 'PLAY_DONE' | 'RECORD' | 'STOP' | 'RECORD_FAILED' | 'UPLOADED' | 'PLAYBACK_DONE' | 'CANCEL'`; `echoReducer(s, e) -> EchoState` (Enter in `playing` stops playback and starts recording; `RECORD_FAILED` → `idle`; `CANCEL` from anywhere → `idle`).
- `lib/keys.ts`: `shouldHandleKey(target: EventTarget | null) -> boolean` (false inside input/textarea/select/contentEditable); `KEYMAP: Record<string, Action>` where `Action = 'play'|'record'|'chorus'|'prev'|'next'|'flag'|'toggleHanzi'|'togglePinyin'|'toggleTranslation'|'toggleDrawer'|'exportAnki'|'replayYou'|'speed075'`; keys: Space→play, Enter→record, c→chorus, ArrowLeft/ArrowRight→prev/next, f→flag, t/p/e→toggles, l→toggleDrawer, a→exportAnki, r→replayYou, s→speed075.
- `store/practice.ts` (zustand, not persisted): `lesson, segments, idx, mode, sessionId, rate, drawerOpen, attemptsThisSegment, lastAttempt: { blob, url, duration, peaks } | null, textPrefs, recordingNow, setters…`.
- `Practice.tsx`: route `/practice/:id`; creates a session on mount (mode echo) and ends it on unmount; owns `ClipPlayer`, `AudioContext`, `Recorder`; implements Echo as described in spec §6 and §7.1; shows "move on" hint when `attemptsThisSegment >= practice.moveOnAfter`; session timer amber ≥ 20 min; auto-hides text while `recordingNow && hideTextWhileRecording`.

- [ ] **Step 1: Failing tests**

`frontend/src/lib/echo.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { echoReducer } from './echo'
describe('echoReducer', () => {
  it('happy path', () => {
    let s = echoReducer('idle', 'PLAY'); expect(s).toBe('playing')
    s = echoReducer(s, 'PLAY_DONE'); expect(s).toBe('idle')
    s = echoReducer(s, 'RECORD'); expect(s).toBe('recording')
    s = echoReducer(s, 'STOP'); expect(s).toBe('uploading')
    s = echoReducer(s, 'UPLOADED'); expect(s).toBe('playback')
    s = echoReducer(s, 'PLAYBACK_DONE'); expect(s).toBe('idle')
  })
  it('Enter during playback interrupts and records', () => { expect(echoReducer('playing', 'RECORD')).toBe('recording') })
  it('record failure returns to idle', () => { expect(echoReducer('recording', 'RECORD_FAILED')).toBe('idle') })
  it('ignores nonsense', () => { expect(echoReducer('idle', 'STOP')).toBe('idle'); expect(echoReducer('uploading', 'RECORD')).toBe('uploading') })
})
```

`frontend/src/lib/keys.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { shouldHandleKey, KEYMAP } from './keys'
describe('keys', () => {
  it('ignores typing targets', () => {
    const input = document.createElement('input'); const div = document.createElement('div'); const ce = document.createElement('div'); ce.contentEditable = 'true'
    expect(shouldHandleKey(input)).toBe(false); expect(shouldHandleKey(div)).toBe(true); expect(shouldHandleKey(ce)).toBe(false); expect(shouldHandleKey(null)).toBe(true)
  })
  it('maps keys', () => { expect(KEYMAP[' ']).toBe('play'); expect(KEYMAP['Enter']).toBe('record'); expect(KEYMAP['l']).toBe('toggleDrawer') })
})
```

- [ ] **Step 2: Run to verify fail** → FAIL

- [ ] **Step 3: Implement pure modules**

`frontend/src/lib/echo.ts`:
```ts
export type EchoState = 'idle' | 'playing' | 'recording' | 'uploading' | 'playback'
export type EchoEvent = 'PLAY' | 'PLAY_DONE' | 'RECORD' | 'STOP' | 'RECORD_FAILED' | 'UPLOADED' | 'PLAYBACK_DONE' | 'CANCEL'
export function echoReducer(s: EchoState, e: EchoEvent): EchoState {
  if (e === 'CANCEL') return 'idle'
  switch (s) {
    case 'idle': return e === 'PLAY' ? 'playing' : e === 'RECORD' ? 'recording' : s
    case 'playing': return e === 'PLAY_DONE' ? 'idle' : e === 'RECORD' ? 'recording' : s
    case 'recording': return e === 'STOP' ? 'uploading' : e === 'RECORD_FAILED' ? 'idle' : s
    case 'uploading': return e === 'UPLOADED' ? 'playback' : e === 'RECORD_FAILED' ? 'idle' : s
    case 'playback': return e === 'PLAYBACK_DONE' ? 'idle' : e === 'RECORD' ? 'recording' : e === 'PLAY' ? 'playing' : s
  }
}
```

`frontend/src/lib/keys.ts`:
```ts
export type Action = 'play' | 'record' | 'chorus' | 'prev' | 'next' | 'flag' | 'toggleHanzi' | 'togglePinyin' | 'toggleTranslation' | 'toggleDrawer' | 'exportAnki' | 'replayYou' | 'speed075'
export const KEYMAP: Record<string, Action> = {
  ' ': 'play', Enter: 'record', c: 'chorus', ArrowLeft: 'prev', ArrowRight: 'next', f: 'flag',
  t: 'toggleHanzi', p: 'togglePinyin', e: 'toggleTranslation', l: 'toggleDrawer', a: 'exportAnki', r: 'replayYou', s: 'speed075',
}
export function shouldHandleKey(target: EventTarget | null): boolean {
  const el = target as HTMLElement | null
  if (!el || !el.tagName) return true
  if (['INPUT', 'TEXTAREA', 'SELECT'].includes(el.tagName)) return false
  return !el.isContentEditable
}
```

- [ ] **Step 4: Practice store**

`frontend/src/store/practice.ts`:
```ts
import { create } from 'zustand'
import type { LessonDetail, Mode, Segment } from '../api/types'
import { defaultTextPrefs, type TextPrefs } from './settings'

export interface LastAttempt { id: number; url: string; duration: number; peaks: Float32Array | null }
interface PracticeState {
  lesson: LessonDetail | null; idx: number; mode: Mode; sessionId: number | null; rate: number; drawerOpen: boolean
  attemptsThisSegment: number; lastAttempt: LastAttempt | null; textPrefs: TextPrefs; recordingNow: boolean; hint: string
  setLesson: (l: LessonDetail) => void; setIdx: (i: number) => void; setMode: (m: Mode) => void; setSession: (id: number | null) => void
  setRate: (r: number) => void; toggleDrawer: () => void; bumpAttempts: () => void; setLastAttempt: (a: LastAttempt | null) => void
  setTextPrefs: (p: TextPrefs) => void; setRecording: (b: boolean) => void; setHint: (h: string) => void
  updateSegment: (s: Segment) => void; replaceSegments: (segs: Segment[]) => void
}
export const usePractice = create<PracticeState>((set) => ({
  lesson: null, idx: 0, mode: 'echo', sessionId: null, rate: 1.0, drawerOpen: true, attemptsThisSegment: 0, lastAttempt: null,
  textPrefs: defaultTextPrefs, recordingNow: false, hint: '',
  setLesson: (lesson) => set({ lesson, idx: 0, attemptsThisSegment: 0, lastAttempt: null }),
  setIdx: (idx) => set({ idx, attemptsThisSegment: 0, lastAttempt: null, hint: '' }),
  setMode: (mode) => set({ mode }), setSession: (sessionId) => set({ sessionId }), setRate: (rate) => set({ rate }),
  toggleDrawer: () => set((s) => ({ drawerOpen: !s.drawerOpen })), bumpAttempts: () => set((s) => ({ attemptsThisSegment: s.attemptsThisSegment + 1 })),
  setLastAttempt: (lastAttempt) => set({ lastAttempt }), setTextPrefs: (textPrefs) => set({ textPrefs }), setRecording: (recordingNow) => set({ recordingNow }), setHint: (hint) => set({ hint }),
  updateSegment: (seg) => set((s) => s.lesson ? { lesson: { ...s.lesson, segments: s.lesson.segments.map((x) => (x.id === seg.id ? seg : x)) } } : {}),
  replaceSegments: (segments) => set((s) => (s.lesson ? { lesson: { ...s.lesson, segments } } : {})),
}))
export const currentSegment = (s: PracticeState): Segment | null => s.lesson?.segments[s.idx] ?? null
```

- [ ] **Step 5: Components and page**

`frontend/src/components/TopBar.tsx`:
```tsx
import type { Mode } from '../api/types'
export default function TopBar({ title, speaker, idx, total, mode, onMode, elapsedS }: { title: string; speaker: string; idx: number; total: number; mode: Mode; onMode: (m: Mode) => void; elapsedS: number }) {
  const mm = String(Math.floor(elapsedS / 60)).padStart(2, '0'), ss = String(Math.floor(elapsedS % 60)).padStart(2, '0')
  return (
    <div className="flex items-center justify-between px-4 py-2 border-b border-line text-sm text-fgdim">
      <span><span className="font-hanzi text-fghi">{speaker && `${speaker} · `}{title}</span> &nbsp; {idx + 1} / {total}</span>
      <span className="flex gap-1">{(['echo', 'chorus', 'flow', 'guided'] as Mode[]).map((m) => (
        <button key={m} onClick={() => onMode(m)} className={`px-2 py-0.5 rounded border ${m === mode ? 'bg-[#1c2a3a] border-accent text-white' : 'border-line'}`}>{m[0].toUpperCase() + m.slice(1)}</button>))}</span>
      <span className={elapsedS >= 1200 ? 'text-warn' : ''}>⏱ {mm}:{ss}</span>
    </div>
  )
}
```

`frontend/src/components/Transport.tsx`:
```tsx
import type { Action } from '../lib/keys'
interface Props { onAction: (a: Action) => void; rate: number; onRate: (r: number) => void; recording: boolean; busy: boolean; flagged: boolean; hint: string; error: string }
export default function Transport({ onAction, rate, onRate, recording, busy, flagged, hint, error }: Props) {
  const b = 'px-3 py-1 rounded bg-panel2 text-sm disabled:opacity-40'
  return (
    <div className="border-t border-line p-3 text-center space-y-1">
      <div className="flex justify-center gap-2 items-center">
        <button className={b} onClick={() => onAction('prev')}>◀</button>
        <button className={b} onClick={() => onAction('play')} disabled={recording}>▶ Space</button>
        <button className={`${b} ${recording ? 'bg-[#5a1f26] text-[#ffd7db]' : ''}`} onClick={() => onAction('record')} disabled={busy}>{recording ? '■ stop' : '● Enter'}</button>
        <button className={b} onClick={() => onAction('chorus')} disabled={recording || busy}>↻ C</button>
        <button className={b} onClick={() => onAction('replayYou')}>▶ R</button>
        <label className="text-xs text-fgdim flex items-center gap-1">{rate.toFixed(2)}×<input type="range" min={0.6} max={1} step={0.05} value={rate} onChange={(e) => onRate(Number(e.target.value))} /></label>
        <button className={b} onClick={() => onAction('speed075')}>0.75×</button>
        <button className={`${b} ${flagged ? 'text-warn' : ''}`} onClick={() => onAction('flag')}>⚑ F</button>
        <button className={b} onClick={() => onAction('toggleHanzi')}>T</button><button className={b} onClick={() => onAction('togglePinyin')}>P</button><button className={b} onClick={() => onAction('toggleTranslation')}>E</button>
        <button className={b} onClick={() => onAction('exportAnki')}>A → Anki</button>
        <button className={b} onClick={() => onAction('next')}>▶</button>
      </div>
      {hint && <p className="text-xs text-warn">{hint}</p>}
      {error && <p className="text-xs text-bad">{error}</p>}
    </div>
  )
}
```

`frontend/src/components/Drawer.tsx` (list; Task 11 adds the actions menu):
```tsx
import type { Segment } from '../api/types'
export function dotClass(seg: Segment, pending: boolean): string {
  if (pending) return 'border border-dashed border-fgdim'
  if (seg.last_score == null) return 'bg-line'
  return seg.last_score >= 0.8 ? 'bg-ok' : seg.last_score >= 0.6 ? 'bg-warn' : 'bg-bad'
}
export default function Drawer({ segments, idx, open, pendingIds, onJump, onToggle }: { segments: Segment[]; idx: number; open: boolean; pendingIds: Set<number>; onJump: (i: number) => void; onToggle: () => void }) {
  if (!open) return <button className="w-6 border-l border-line text-fgdim text-xs" onClick={onToggle} title="Open lesson list (L)">▸</button>
  return (
    <aside className="w-80 border-l border-line overflow-y-auto">
      <div className="flex justify-between px-3 py-2 text-[10px] uppercase tracking-widest text-fgdim"><span>Lesson</span><button onClick={onToggle}>◂ L</button></div>
      {segments.map((s, i) => (
        <button key={s.id} onClick={() => onJump(i)} title={`${s.text}${s.last_score != null ? `\nlast ${Math.round(s.last_score * 100)} · best ${Math.round((s.best_score ?? 0) * 100)}` : ''}`}
          className={`w-full flex items-center gap-2 px-3 py-1 text-left text-sm ${i === idx ? 'bg-[#1c2a3a] text-fghi' : 'text-fgdim'}`}>
          <span className="w-5 text-right text-[10px]">{s.idx + 1}</span>
          <span className={`w-2 h-2 rounded-full flex-none ${dotClass(s, pendingIds.has(s.id))}`} />
          <span className="truncate font-hanzi">{s.text}</span>
          {s.difficulty_flag && <span className="text-warn">⚑</span>}
        </button>))}
    </aside>
  )
}
```

`frontend/src/pages/Practice.tsx` (Echo only; Chorus/Flow/Guided arrive in Task 10, drawer actions and export in Task 11):
```tsx
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import { api } from '../api/client'
import { ClipPlayer, peaks as peaksOf, playSequence } from '../audio/player'
import { Recorder, toWav16k } from '../audio/recorder'
import { findSilenceEnd } from '../audio/pcm'
import Drawer from '../components/Drawer'
import Sentence from '../components/Sentence'
import TopBar from '../components/TopBar'
import Transport from '../components/Transport'
import TwoTrack from '../components/TwoTrack'
import { echoReducer, type EchoState } from '../lib/echo'
import { KEYMAP, shouldHandleKey, type Action } from '../lib/keys'
import { usePractice, currentSegment } from '../store/practice'
import { useSettings, defaultTextPrefs } from '../store/settings'

export default function Practice() {
  const { id } = useParams()
  const lessonId = Number(id)
  const st = usePractice()
  const settings = useSettings()
  const seg = usePractice(currentSegment)
  const player = useMemo(() => new ClipPlayer(), [])
  const ctxRef = useRef<AudioContext | null>(null)
  const recRef = useRef<Recorder | null>(null)
  const [echo, setEcho] = useState<EchoState>('idle')
  const echoRef = useRef<EchoState>('idle'); echoRef.current = echo
  const dispatch = useCallback((e: Parameters<typeof echoReducer>[1]) => setEcho((s) => echoReducer(s, e)), [])
  const [refPeaks, setRefPeaks] = useState<Float32Array | null>(null)
  const [refHead, setRefHead] = useState<number | null>(null)
  const [youHead, setYouHead] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [started] = useState(() => Date.now())
  const [elapsed, setElapsed] = useState(0)
  const vadTimer = useRef<number | null>(null)

  useEffect(() => { const t = setInterval(() => setElapsed((Date.now() - started) / 1000), 1000); return () => clearInterval(t) }, [started])

  useEffect(() => {
    let sid: number | null = null
    api.lessons.get(lessonId).then((l) => { st.setLesson(l); st.setTextPrefs(settings.textPrefs[String(lessonId)] ?? defaultTextPrefs); st.setRate(settings.practice.defaultRate) })
    api.sessions.create(lessonId, 'echo').then((s) => { sid = s.id; st.setSession(s.id) })
    return () => { if (sid) api.sessions.end(sid); player.stop() }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lessonId])

  useEffect(() => {
    if (!seg) return
    const url = api.segments.audioUrl(seg.id)
    player.preload(url); player.peaksFor(url, 400).then(setRefPeaks).catch(() => setRefPeaks(null))
    const nxt = st.lesson?.segments[st.idx + 1]; if (nxt) player.preload(api.segments.audioUrl(nxt.id))
    setRefHead(null); setYouHead(null)
  }, [seg?.id]) // eslint-disable-line react-hooks/exhaustive-deps

  const refDuration = seg ? seg.end_s - seg.start_s : 0

  async function playRef() {
    if (!seg) return
    dispatch('PLAY')
    try { await player.play(api.segments.audioUrl(seg.id), st.rate, setRefHead) } finally { if (echoRef.current === 'playing') dispatch('PLAY_DONE') }
  }
  async function startRecording() {
    if (!seg) return
    player.stop(); dispatch('RECORD'); st.setRecording(true); setError('')
    try {
      ctxRef.current ??= new AudioContext()
      recRef.current ??= new Recorder(ctxRef.current)
      await recRef.current.start()
      const tick = () => {
        const r = recRef.current!; const idx = findSilenceEnd(r.snapshot(), r.sampleRate)
        if (idx != null) stopRecording(); else vadTimer.current = window.setTimeout(tick, 200)
      }
      vadTimer.current = window.setTimeout(tick, 400)
    } catch (e) { st.setRecording(false); setError(`Microphone unavailable: ${(e as Error).message}`); dispatch('RECORD_FAILED') }
  }
  async function stopRecording() {
    if (echoRef.current !== 'recording' || !seg) return
    if (vadTimer.current) { clearTimeout(vadTimer.current); vadTimer.current = null }
    dispatch('STOP'); st.setRecording(false)
    const rec = recRef.current!
    const samples = rec.stop()
    const wav = toWav16k(samples, rec.sampleRate)
    const url = URL.createObjectURL(wav)
    const duration = samples.length / rec.sampleRate
    const you = { id: 0, url, duration, peaks: peaksOf(samples, 400) }
    st.setLastAttempt(you); st.bumpAttempts()
    if (st.attemptsThisSegment + 1 >= settings.practice.moveOnAfter) st.setHint('Several tries on this one. Move on and come back later.')
    const upload = api.segments.postAttempt(seg.id, wav, { session_id: st.sessionId ?? undefined, mode: 'echo' })
      .then((a) => st.setLastAttempt({ ...you, id: a.id })).catch((e) => setError(`Upload failed: ${(e as Error).message}`))
    dispatch('UPLOADED')
    await playSequence(player, [{ url: api.segments.audioUrl(seg.id), rate: st.rate, onTime: setRefHead }, { url, rate: 1, onTime: setYouHead }])
    dispatch('PLAYBACK_DONE'); await upload
  }
  async function loopSyllable(i: number) {
    const span = seg?.ref_alignment_json?.[i]; if (!seg || !span) return
    const a = player['el'](api.segments.audioUrl(seg.id, 'wav')) as HTMLAudioElement
    a.currentTime = Math.max(0, span.start - seg.start_s); a.playbackRate = st.rate; await a.play()
    const stopAt = span.end - seg.start_s; const h = setInterval(() => { if (a.currentTime >= stopAt) { a.pause(); clearInterval(h) } }, 20)
  }
  function act(a: Action) {
    const prefs = st.textPrefs
    const savePrefs = (p: typeof prefs) => { st.setTextPrefs(p); settings.setTextPrefs(lessonId, p) }
    switch (a) {
      case 'play': return playRef()
      case 'record': return echo === 'recording' ? stopRecording() : startRecording()
      case 'prev': return st.setIdx(Math.max(0, st.idx - 1))
      case 'next': return st.setIdx(Math.min((st.lesson?.segments.length ?? 1) - 1, st.idx + 1))
      case 'toggleHanzi': return savePrefs({ ...prefs, hanzi: !prefs.hanzi })
      case 'togglePinyin': return savePrefs({ ...prefs, pinyin: !prefs.pinyin })
      case 'toggleTranslation': return savePrefs({ ...prefs, translation: !prefs.translation })
      case 'toggleDrawer': return st.toggleDrawer()
      case 'speed075': return st.setRate(st.rate === 0.75 ? 1 : 0.75)
      case 'replayYou': return st.lastAttempt && player.play(st.lastAttempt.url, 1, setYouHead)
      case 'flag': return seg && api.segments.patch(seg.id, { difficulty_flag: !seg.difficulty_flag }).then(st.updateSegment)
      default: return // chorus, exportAnki: Tasks 10 and 11
    }
  }
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if (!shouldHandleKey(e.target)) return; const a = KEYMAP[e.key]; if (a) { e.preventDefault(); act(a) } }
    window.addEventListener('keydown', h); return () => window.removeEventListener('keydown', h)
  })

  if (!st.lesson || !seg) return <div className="p-8 text-fgdim">Loading…</div>
  const hide = st.recordingNow && settings.practice.hideTextWhileRecording
  return (
    <div className="h-full flex flex-col">
      <TopBar title={st.lesson.title} speaker={st.lesson.speaker} idx={st.idx} total={st.lesson.segments.length} mode={st.mode} onMode={st.setMode} elapsedS={elapsed} />
      <div className="flex-1 flex min-h-0">
        <main className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            <Sentence text={seg.text} words={seg.words_json} showHanzi={st.textPrefs.hanzi && !hide} showPinyin={st.textPrefs.pinyin && !hide} translation={seg.translation} showTranslation={st.textPrefs.translation && !hide} />
            <TwoTrack segment={seg} refPeaks={refPeaks} refDuration={refDuration} refPlayhead={refHead}
              youPeaks={st.lastAttempt?.peaks ?? null} youDuration={st.lastAttempt?.duration ?? 0} youPlayhead={youHead}
              onPlayRef={playRef} onPlayYou={() => act('replayYou')} onLoopSyllable={loopSyllable} />
          </div>
          <Transport onAction={act} rate={st.rate} onRate={st.setRate} recording={echo === 'recording'} busy={echo === 'uploading'} flagged={seg.difficulty_flag} hint={st.hint} error={error} />
        </main>
        <Drawer segments={st.lesson.segments} idx={st.idx} open={st.drawerOpen} pendingIds={new Set()} onJump={st.setIdx} onToggle={st.toggleDrawer} />
      </div>
    </div>
  )
}
```

Add route `/practice/:id` → `<Practice />` in `App.tsx`.

- [ ] **Step 6: Run tests, then the manual Echo check**

Run: `cd frontend && npx vitest run` → pass. Then `make dev`, open a ready lesson. Checklist: Space plays with the playhead moving; Enter records, text hides, stopping by Enter or by 1.2 s of silence; reference then your take play back to back; the You track shows a waveform and cells; ArrowRight advances and preloads; T/P/E toggles persist after reload; pressing keys inside the browser URL bar does nothing in the app.

- [ ] **Step 7: Commit**

```bash
git add frontend && git commit -m "feat(frontend): practice page with stage, drawer and Echo mode"
```

---

### Task 10: Chorus, Flow and Guided modes

**Files:**
- Create: `frontend/src/lib/flow.ts`, `frontend/src/lib/flow.test.ts`, `frontend/src/lib/guided.ts`, `frontend/src/lib/guided.test.ts`, `frontend/src/components/FlowView.tsx`, `frontend/src/components/FlowSummary.tsx`
- Modify: `frontend/src/pages/Practice.tsx`

**Interfaces:**
- `lib/flow.ts`: `FlowSub = 'after' | 'along'`; `ActualPlay { segmentId: number; idx: number; playStart: number; playEnd?: number; refDuration: number }`; `sliceRangesFromActual(actual: ActualPlay[], sub, gapFactor, slack = 0.15) -> { segmentId; idx; t0; t1 }[]` (skips entries without `playEnd`; `after`: `[playEnd - slack, playEnd + refDuration*gapFactor + slack]`; `along`: `[playStart - slack, playEnd + slack]`); `gapAfter(refDuration, gapFactor) -> number`; `FlowResult { segmentId; idx; attemptId: number | null; url: string; duration: number }`.
- `lib/guided.ts`: `GuidedStep = 'listen' | 'whisper' | 'record'`; `nextGuidedStep(step) -> GuidedStep | null`; `guidedText(step) -> { showText: boolean; label: string }`.
- `Practice.tsx` gains: Chorus (`c`): play clip `chorusPasses` times with 300 ms gaps, recording from the start of the last pass to its end + 0.3 s, then upload with `mode:'chorus'` and back-to-back playback; Flow: range picker (from current idx to end by default), continuous recording, sequential plays recording `ActualPlay`, slicing on completion or stop, uploads with `mode:'flow'`, drawer-as-stage view while running, summary after; Guided: per sentence listen → whisper (one chorus pass, text visible, no upload) → record (text hidden) then auto-advance.

- [ ] **Step 1: Failing tests**

`frontend/src/lib/flow.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { sliceRangesFromActual, gapAfter } from './flow'
const A = [
  { segmentId: 1, idx: 0, playStart: 10.0, playEnd: 12.0, refDuration: 2.0 },
  { segmentId: 2, idx: 1, playStart: 14.5, playEnd: 16.0, refDuration: 1.5 },
  { segmentId: 3, idx: 2, playStart: 18.0, refDuration: 1.0 },          // interrupted
]
describe('flow slices', () => {
  it('after: gap after each clip, skips unfinished', () => {
    const r = sliceRangesFromActual(A, 'after', 1.1)
    expect(r.length).toBe(2)
    expect(r[0]).toEqual({ segmentId: 1, idx: 0, t0: 11.85, t1: 14.35 })
  })
  it('along: spans the clip itself', () => {
    expect(sliceRangesFromActual(A, 'along', 1.1)[1]).toEqual({ segmentId: 2, idx: 1, t0: 14.35, t1: 16.15 })
  })
  it('gapAfter', () => { expect(gapAfter(2, 1.1)).toBeCloseTo(2.2) })
})
```

`frontend/src/lib/guided.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { nextGuidedStep, guidedText } from './guided'
describe('guided', () => {
  it('progresses listen → whisper → record → null', () => {
    expect(nextGuidedStep('listen')).toBe('whisper'); expect(nextGuidedStep('whisper')).toBe('record'); expect(nextGuidedStep('record')).toBeNull()
  })
  it('hides text only when recording', () => { expect(guidedText('whisper').showText).toBe(true); expect(guidedText('record').showText).toBe(false) })
})
```

- [ ] **Step 2: Run to verify fail** → FAIL

- [ ] **Step 3: Implement pure modules**

`frontend/src/lib/flow.ts`:
```ts
export type FlowSub = 'after' | 'along'
export interface ActualPlay { segmentId: number; idx: number; playStart: number; playEnd?: number; refDuration: number }
export interface SliceRange { segmentId: number; idx: number; t0: number; t1: number }
export interface FlowResult { segmentId: number; idx: number; attemptId: number | null; url: string; duration: number }
const r3 = (x: number) => Math.round(x * 1000) / 1000
export const gapAfter = (refDuration: number, gapFactor: number) => refDuration * gapFactor
export function sliceRangesFromActual(actual: ActualPlay[], sub: FlowSub, gapFactor: number, slack = 0.15): SliceRange[] {
  return actual.filter((a) => a.playEnd != null).map((a) => sub === 'after'
    ? { segmentId: a.segmentId, idx: a.idx, t0: r3(a.playEnd! - slack), t1: r3(a.playEnd! + gapAfter(a.refDuration, gapFactor) + slack) }
    : { segmentId: a.segmentId, idx: a.idx, t0: r3(a.playStart - slack), t1: r3(a.playEnd! + slack) })
}
```

`frontend/src/lib/guided.ts`:
```ts
export type GuidedStep = 'listen' | 'whisper' | 'record'
export const nextGuidedStep = (s: GuidedStep): GuidedStep | null => (s === 'listen' ? 'whisper' : s === 'whisper' ? 'record' : null)
export const guidedText = (s: GuidedStep) => ({
  listen: { showText: true, label: 'Listen once' }, whisper: { showText: true, label: 'Whisper along (text visible)' }, record: { showText: false, label: 'Now record, text hidden' },
}[s])
```

- [ ] **Step 4: Flow components**

`frontend/src/components/FlowView.tsx`:
```tsx
import type { Segment } from '../api/types'
import Sentence from './Sentence'
import { dotClass } from './Drawer'
export default function FlowView({ segments, current, done, pending, micPeak, sub, showText }: { segments: Segment[]; current: number; done: Map<number, number | null>; pending: Set<number>; micPeak: number; sub: 'after' | 'along'; showText: boolean }) {
  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-1">
      {segments.map((s, i) => {
        const isCur = i === current
        return (
          <div key={s.id} id={`flow-${s.id}`} className={`flex gap-3 items-start px-3 py-1 rounded ${isCur ? 'bg-[#1c2a3a] py-3' : ''}`}>
            <span className="w-6 text-right text-[10px] text-fgdim pt-1">{s.idx + 1}</span>
            <span className={`w-2 h-2 mt-2 rounded-full flex-none ${dotClass({ ...s, last_score: done.get(s.id) ?? s.last_score }, pending.has(s.id))}`} />
            {isCur ? (
              <div className="flex-1">
                <Sentence text={s.text} words={s.words_json} showHanzi={showText} showPinyin={showText} />
                <div className="flex items-center gap-2 mt-2 pl-4"><span className="w-2.5 h-2.5 rounded-full bg-bad shadow-[0_0_8px_#d9534f]" />
                  <div className="h-2 flex-1 bg-panel2 rounded overflow-hidden"><div className="h-full bg-you" style={{ width: `${Math.min(100, micPeak * 300)}%` }} /></div>
                  <span className="text-[10px] text-fgdim">{sub === 'after' ? 'your turn' : 'speak along'}</span></div>
              </div>
            ) : <span className={`font-hanzi truncate ${i < current ? 'text-fgdim' : 'text-fg'}`}>{s.text}</span>}
          </div>)
      })}
    </div>
  )
}
```

`frontend/src/components/FlowSummary.tsx`:
```tsx
import type { Segment } from '../api/types'
import type { FlowResult } from '../lib/flow'
interface Props { segments: Segment[]; results: FlowResult[]; elapsedS: number; onReplayAll: () => void; onRunAgain: () => void; onEcho: (idx: number) => void; onChorus: (idx: number) => void; onFlagWeakest: () => void; onExportWeakest: () => void; onDone: () => void; onPlayPair: (r: FlowResult) => void }
export default function FlowSummary(p: Props) {
  const byId = new Map(p.segments.map((s) => [s.id, s]))
  const scored = p.results.filter((r) => byId.get(r.segmentId)?.last_score != null)
  const mean = scored.length ? scored.reduce((a, r) => a + (byId.get(r.segmentId)!.last_score ?? 0), 0) / scored.length : null
  const weakest = [...scored].sort((a, b) => (byId.get(a.segmentId)!.last_score ?? 0) - (byId.get(b.segmentId)!.last_score ?? 0)).slice(0, 3)
  return (
    <div className="p-6 space-y-4">
      <h2 className="text-fghi">Flow finished · {p.results.length} sentences · {Math.round(p.elapsedS / 60)} min {Math.round(p.elapsedS % 60)} s</h2>
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-bg border border-line rounded p-3"><div className="text-2xl text-fghi">{mean != null ? Math.round(mean * 100) : '—'}</div><div className="text-fgdim text-sm">{mean != null ? 'mean score' : 'scores arrive in Phase 2'}</div></div>
        <div className="bg-bg border border-line rounded p-3 text-sm">
          <div className="text-[10px] uppercase tracking-widest text-fgdim mb-1">{scored.length ? 'weakest, drill these' : 'replay each line'}</div>
          {(scored.length ? weakest : p.results).map((r) => (
            <div key={r.segmentId} className="flex items-center gap-2 py-0.5"><span className="font-hanzi truncate flex-1">{byId.get(r.segmentId)?.text}</span>
              <button className="btn" onClick={() => p.onPlayPair(r)}>▶ ref+you</button><button className="btn" onClick={() => p.onEcho(r.idx)}>Echo</button><button className="btn" onClick={() => p.onChorus(r.idx)}>Chorus</button></div>))}
        </div>
      </div>
      <div className="flex gap-2 justify-center">
        <button className="btn" onClick={p.onReplayAll}>▶ replay whole flow</button><button className="btn" onClick={p.onRunAgain}>↻ run again</button>
        <button className="btn" onClick={p.onFlagWeakest} disabled={!scored.length}>⚑ flag weakest 3</button><button className="btn" onClick={p.onExportWeakest} disabled={!scored.length}>A → Anki weakest 3</button>
        <button className="btn" onClick={p.onDone}>done</button>
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Wire the modes into `Practice.tsx`**

Add state and handlers (inside the component; imports for `FlowView`, `FlowSummary`, `sliceRangesFromActual`, `gapAfter`, `nextGuidedStep`, `guidedText`, `rms`):

```tsx
  // --- Chorus ---
  async function chorus(passes = settings.practice.chorusPasses) {
    if (!seg || echoRef.current !== 'idle') return
    const url = api.segments.audioUrl(seg.id)
    for (let i = 0; i < passes - 1; i++) { await player.play(url, st.rate, setRefHead); await new Promise((r) => setTimeout(r, 300)) }
    await startRecordingRaw()                                        // no VAD in chorus
    await player.play(url, st.rate, setRefHead)
    await new Promise((r) => setTimeout(r, 300))
    await finishRecording('chorus')
  }
  // startRecordingRaw/finishRecording are the VAD-free halves of startRecording/stopRecording from Task 9:
  // extract them so Echo calls startRecordingRaw() + VAD timer, and stopRecording() calls finishRecording('echo').

  // --- Flow ---
  const [flow, setFlow] = useState<{ running: boolean; sub: 'after' | 'along'; from: number; to: number; current: number; results: FlowResult[]; done: Map<number, number | null>; pending: Set<number>; micPeak: number; summary: boolean; startedAt: number }>(
    { running: false, sub: 'after', from: 0, to: 0, current: 0, results: [], done: new Map(), pending: new Set(), micPeak: 0, summary: false, startedAt: 0 })
  const flowStop = useRef(false)
  async function runFlow(from: number, to: number, sub: 'after' | 'along') {
    if (!st.lesson) return
    flowStop.current = false
    ctxRef.current ??= new AudioContext(); recRef.current ??= new Recorder(ctxRef.current)
    const rec = recRef.current, ctx = ctxRef.current
    setFlow((f) => ({ ...f, running: true, sub, from, to, current: from, results: [], done: new Map(), pending: new Set(), summary: false, startedAt: Date.now() }))
    st.setRecording(true)
    try { await rec.start() } catch (e) { setError(`Microphone unavailable: ${(e as Error).message}`); st.setRecording(false); setFlow((f) => ({ ...f, running: false })); return }
    const meter = setInterval(() => { const s = rec.snapshot(); setFlow((f) => ({ ...f, micPeak: rms(s.subarray(Math.max(0, s.length - 2048))) })) }, 100)
    const actual: ActualPlay[] = []
    for (let i = from; i <= to && !flowStop.current; i++) {
      const s = st.lesson.segments[i]
      setFlow((f) => ({ ...f, current: i })); document.getElementById(`flow-${s.id}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
      const a: ActualPlay = { segmentId: s.id, idx: i, playStart: ctx.currentTime, refDuration: s.end_s - s.start_s }
      actual.push(a)
      await player.play(api.segments.audioUrl(s.id), st.rate)
      a.playEnd = ctx.currentTime
      if (sub === 'after') await new Promise((r) => setTimeout(r, gapAfter(a.refDuration, settings.practice.flowGapFactor) * 1000))
      await new Promise((r) => setTimeout(r, 300))
    }
    clearInterval(meter)
    await new Promise((r) => setTimeout(r, 200))
    rec.stop(); st.setRecording(false)
    const ranges = sliceRangesFromActual(actual, sub, settings.practice.flowGapFactor)
    const results: FlowResult[] = []
    setFlow((f) => ({ ...f, pending: new Set(ranges.map((r) => r.segmentId)) }))
    for (const r of ranges) {
      const samples = rec.slice(r.t0, r.t1)
      const wav = toWav16k(samples, rec.sampleRate)
      const url = URL.createObjectURL(wav)
      let attemptId: number | null = null
      try { attemptId = (await api.segments.postAttempt(r.segmentId, wav, { session_id: st.sessionId ?? undefined, mode: 'flow' })).id } catch (e) { setError(`Upload failed: ${(e as Error).message}`) }
      results.push({ segmentId: r.segmentId, idx: r.idx, attemptId, url, duration: samples.length / rec.sampleRate })
      setFlow((f) => { const pending = new Set(f.pending); pending.delete(r.segmentId); return { ...f, pending, results: [...results] } })
    }
    const fresh = await api.lessons.get(lessonId); st.replaceSegments(fresh.segments)
    setFlow((f) => ({ ...f, running: false, summary: true }))
  }
  function stopFlow() { flowStop.current = true; player.stop() }

  // --- Guided ---
  const [guided, setGuided] = useState<GuidedStep>('listen')
  async function guidedNext() {
    if (!seg) return
    if (guided === 'listen') { await playRef(); setGuided('whisper'); return }
    if (guided === 'whisper') { await startRecordingRaw(); await player.play(api.segments.audioUrl(seg.id), st.rate, setRefHead); recRef.current!.stop(); st.setRecording(false); dispatch('CANCEL'); setGuided('record'); return }
    await startRecording()   // echo recording with VAD; on PLAYBACK_DONE in guided mode, advance (effect below)
  }
  useEffect(() => { if (st.mode === 'guided' && echo === 'idle' && guided === 'record' && st.lastAttempt) { setGuided('listen'); act('next') } }, [echo]) // eslint-disable-line react-hooks/exhaustive-deps
```

Mode-dependent bindings in `act`: `'record'` in guided mode calls `guidedNext()`; `'chorus'` calls `chorus()`; in flow mode `'record'` starts `runFlow(st.idx, st.lesson.segments.length - 1, flow.sub)` when not running and `stopFlow()` when running. Mode switch to flow renders a small range form (from/to selects, after/along toggle, Start) above the stage. Rendering: when `flow.running`, replace `<main>` content with `<FlowView … showText={!(settings.practice.hideTextWhileRecording && flow.sub === 'after')} />` and a reduced transport (⏸ not implemented in v1; ■ stop · skip = `player.stop()` · speed · after/along); when `flow.summary`, render `<FlowSummary … />` with `onPlayPair = (r) => playSequence(player, [{url: ref, rate}, {url: r.url, rate: 1}])`, `onEcho = (i) => { st.setMode('echo'); st.setIdx(i); setFlow(f => ({...f, summary:false})) }`, `onChorus = (i) => { … then chorus() }`, `onReplayAll` = `playSequence` over all results interleaved, `onRunAgain = () => runFlow(flow.from, flow.to, flow.sub)`, `onFlagWeakest` = PATCH flag on the three weakest, `onExportWeakest` = Task 11's `exportToAnki` on each. In guided mode the transport's record button label shows `guidedText(guided).label` and the Sentence uses `guidedText(guided).showText && !hide`.

- [ ] **Step 6: Run tests and the manual check**

Run: `cd frontend && npx vitest run` → pass. Manual: Chorus plays 5 passes with the red indicator on the last and uploads one attempt tagged chorus (check `GET /segments/{id}/attempts`); Flow over 3 sentences in `after` mode records continuously, then the drawer dots flip from dashed to grey and the summary lists 3 lines with working ▶ ref+you; stopping Flow mid-run submits only finished lines; Guided goes listen → whisper (text visible) → record (text hidden) and advances.

- [ ] **Step 7: Commit**

```bash
git add frontend && git commit -m "feat(frontend): chorus, flow and guided modes with flow summary"
```

---

### Task 11: Drawer actions (edit, resplit, merge), Anki export

**Files:**
- Create: `frontend/src/anki/export.ts`, `frontend/src/anki/export.test.ts`, `frontend/src/components/EditDialog.tsx`
- Modify: `frontend/src/components/Drawer.tsx`, `frontend/src/pages/Practice.tsx`

**Interfaces:**
- `anki/export.ts`: `buildExportNote(seg: Segment, mp3b64: string, cfg: ExportNote) -> AddNote` (fields mapped; pinyin from `words_json` joined by spaces; tags `['shadow']`; `audio: [{ filename: 'shadow_<id>.mp3', data, fields: [cfg.fields.audio] }]`; `options: { allowDuplicate: false, duplicateScope: 'deck' }`); `exportToAnki(seg, ankiUrl, cfg) -> Promise<number>` fetching `api.segments.audioUrl(seg.id, 'mp3')`, base64-encoding, `addNote`; on an AnkiConnect "duplicate" error, re-asks via `window.confirm` and retries with `allowDuplicate: true`.
- Drawer gains a `⋯` menu per row: Edit text, Split here (opens the edit dialog in split mode where clicking a character chooses the index), Merge with next.
- `EditDialog`: `{ segment, mode: 'edit' | 'split', onSave(text), onSplit(at), onClose }`.

- [ ] **Step 1: Failing test**

`frontend/src/anki/export.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { buildExportNote } from './export'
const seg = { id: 12, lesson_id: 1, idx: 0, start_s: 0, end_s: 1, text: '你好。', translation: 'Hello.', words_json: [{ word: '你好', pinyin: 'nǐhǎo', tones: [2, 3], char_from: 0, char_to: 1, syllables: [] }], ref_alignment_json: null, difficulty_flag: false, anki_note_id: null, last_score: null, best_score: null, attempts: 0 }
describe('buildExportNote', () => {
  it('maps fields, pinyin and audio', () => {
    const n = buildExportNote(seg, 'QUJD', { deckName: 'Shadow', modelName: 'Mining', fields: { sentence: 'Sentence', pinyin: 'Reading', translation: 'Meaning', audio: 'Audio' } })
    expect(n.fields).toEqual({ Sentence: '你好。', Reading: 'nǐhǎo', Meaning: 'Hello.' })
    expect(n.audio![0]).toEqual({ filename: 'shadow_12.mp3', data: 'QUJD', fields: ['Audio'] })
    expect(n.tags).toEqual(['shadow']); expect(n.options!.allowDuplicate).toBe(false)
  })
})
```

- [ ] **Step 2: Run to verify fail** → FAIL

- [ ] **Step 3: Implement export**

`frontend/src/anki/export.ts`:
```ts
import { api } from '../api/client'
import type { Segment } from '../api/types'
import type { ExportNote } from '../store/settings'
import { anki, type AddNote } from './client'

export function buildExportNote(seg: Segment, mp3b64: string, cfg: ExportNote, allowDuplicate = false): AddNote {
  const fields: Record<string, string> = { [cfg.fields.sentence]: seg.text }
  if (cfg.fields.pinyin) fields[cfg.fields.pinyin] = (seg.words_json ?? []).map((w) => w.pinyin).join(' ')
  if (cfg.fields.translation && seg.translation) fields[cfg.fields.translation] = seg.translation
  return { deckName: cfg.deckName, modelName: cfg.modelName, fields, tags: ['shadow'],
    options: { allowDuplicate, duplicateScope: 'deck' }, audio: [{ filename: `shadow_${seg.id}.mp3`, data: mp3b64, fields: [cfg.fields.audio] }] }
}

async function blobToBase64(b: Blob): Promise<string> {
  const bytes = new Uint8Array(await b.arrayBuffer()); let s = ''
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000))
  return btoa(s)
}

export async function exportToAnki(seg: Segment, ankiUrl: string, cfg: ExportNote): Promise<number> {
  const mp3 = await (await fetch(api.segments.audioUrl(seg.id, 'mp3'))).blob()
  const b64 = await blobToBase64(mp3)
  try { return await anki(ankiUrl).addNote(buildExportNote(seg, b64, cfg)) }
  catch (e) {
    if (/duplicate/i.test((e as Error).message) && window.confirm('This sentence already exists in Anki. Add anyway?')) return anki(ankiUrl).addNote(buildExportNote(seg, b64, cfg, true))
    throw e
  }
}
```

- [ ] **Step 4: Edit dialog and drawer menu**

`frontend/src/components/EditDialog.tsx`:
```tsx
import { useState } from 'react'
import type { Segment } from '../api/types'
export default function EditDialog({ segment, mode, onSave, onSplit, onClose }: { segment: Segment; mode: 'edit' | 'split'; onSave: (t: string) => void; onSplit: (at: number) => void; onClose: () => void }) {
  const [text, setText] = useState(segment.text)
  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center" onClick={onClose}>
      <div className="bg-panel border border-line rounded p-4 w-[520px] space-y-3" onClick={(e) => e.stopPropagation()}>
        {mode === 'edit' ? (<>
          <h3 className="text-fghi">Edit sentence</h3>
          <textarea className="inp w-full font-hanzi text-lg" rows={3} value={text} onChange={(e) => setText(e.target.value)} />
          <div className="flex justify-end gap-2"><button className="btn" onClick={onClose}>Cancel</button><button className="btn" onClick={() => onSave(text)}>Save and re-align</button></div>
        </>) : (<>
          <h3 className="text-fghi">Click the first character of the second half</h3>
          <p className="font-hanzi text-2xl leading-loose">{[...segment.text].map((ch, i) => (
            <button key={i} className="hover:bg-[#1c2a3a] rounded px-0.5" disabled={i === 0} onClick={() => onSplit(i)}>{ch}</button>))}</p>
          <div className="flex justify-end"><button className="btn" onClick={onClose}>Cancel</button></div>
        </>)}
      </div>
    </div>
  )
}
```

In `Drawer.tsx` add props `onEdit(i)`, `onSplit(i)`, `onMerge(i)` and per row a `⋯` button opening a tiny inline menu with the three actions (plain buttons, `stopPropagation` on click). In `Practice.tsx`: state `dialog: { mode: 'edit' | 'split'; idx: number } | null`; handlers `onSave = (t) => api.segments.patch(seg.id, { text: t }).then((s) => { st.updateSegment(s); setDialog(null) })`, `onSplit = (at) => api.segments.resplit(seg.id, at).then(() => api.lessons.get(lessonId)).then((l) => { st.replaceSegments(l.segments); setDialog(null) })`, `onMerge = (i) => api.segments.mergeNext(segments[i].id).then(() => api.lessons.get(lessonId)).then((l) => st.replaceSegments(l.segments))`; `act('exportAnki')` → if `settings.exportNote` is null show error "Configure the export note type in Settings", else `exportToAnki(seg, settings.ankiUrl, settings.exportNote).then(() => st.setHint('Sent to Anki')).catch((e) => setError(e.message))`.

- [ ] **Step 5: Run tests and manual check**

Run: `cd frontend && npx vitest run` → pass. Manual: edit a sentence's text and see the cells and clip update; split one sentence and merge it back; press A on a sentence and find the new note in Anki's browser with audio playing.

- [ ] **Step 6: Commit**

```bash
git add frontend && git commit -m "feat(frontend): drawer edit/split/merge and Anki export"
```

---

### Task 12: Review and Stats pages, production build, acceptance checklist

**Files:**
- Create: `frontend/src/pages/Review.tsx`, `frontend/src/pages/Stats.tsx`, `frontend/src/lib/stats.ts`, `frontend/src/lib/stats.test.ts`, `docs/phase1-acceptance.md`
- Modify: `frontend/src/App.tsx`, `.gitignore` (already ignores `frontend/dist`)

**Interfaces:**
- `lib/stats.ts`: `flaggedFirst(lessons: LessonDetail[]) -> { lesson: Lesson; segment: Segment }[]` (flagged or `last_score < 0.6`, oldest lesson first); `activityBars(days: {date; minutes; attempts}[]) -> { label: string; minutes: number; attempts: number }[]` (label = weekday letter).
- `Review.tsx`: loads every ready lesson's detail, lists `flaggedFirst` rows with "Practise" (navigates to `/practice/:lesson?seg=idx`; `Practice.tsx` reads `seg` from the query string to set `idx`) and a bulk "Send all to Anki" button using `exportToAnki`.
- `Stats.tsx`: four panels: Activity (minutes and attempts per day, last 30 days), Sentences (`regressed` and `by_last`, empty state "No scores yet"), Characters, Tones (empty states). **Implementer: load the `dataviz` skill before writing the chart component** and follow its palette rules on top of the dark theme.

- [ ] **Step 1: Failing test**

`frontend/src/lib/stats.test.ts`:
```ts
import { describe, it, expect } from 'vitest'
import { flaggedFirst, activityBars } from './stats'
import type { LessonDetail } from '../api/types'
const L = (id: number, created: string, segs: Partial<LessonDetail['segments'][number]>[]): LessonDetail => ({
  id, title: 't', speaker: '', source_type: 'upload', source_ref: '', duration_s: 0, created_at: created, status: 'ready', error: null, segment_count: segs.length, practised_count: 0, mean_last_score: null,
  segments: segs.map((s, i) => ({ id: id * 10 + i, lesson_id: id, idx: i, start_s: 0, end_s: 1, text: 'x', translation: null, words_json: null, ref_alignment_json: null, difficulty_flag: false, anki_note_id: null, last_score: null, best_score: null, attempts: 0, ...s })),
})
describe('stats helpers', () => {
  it('flaggedFirst picks flagged or weak, oldest lesson first', () => {
    const rows = flaggedFirst([L(2, '2026-02-01', [{ difficulty_flag: true }]), L(1, '2026-01-01', [{ last_score: 0.5 }, { last_score: 0.9 }])])
    expect(rows.map((r) => r.segment.id)).toEqual([10, 20])
  })
  it('activityBars labels weekdays', () => {
    expect(activityBars([{ date: '2026-10-05', minutes: 3, attempts: 2 }])[0]).toEqual({ label: 'M', minutes: 3, attempts: 2 })
  })
})
```

- [ ] **Step 2: Run to verify fail** → FAIL

- [ ] **Step 3: Implement**

`frontend/src/lib/stats.ts`:
```ts
import type { Lesson, LessonDetail, Segment } from '../api/types'
export function flaggedFirst(lessons: LessonDetail[]): { lesson: Lesson; segment: Segment }[] {
  return [...lessons].sort((a, b) => a.created_at.localeCompare(b.created_at))
    .flatMap((l) => l.segments.filter((s) => s.difficulty_flag || (s.last_score != null && s.last_score < 0.6)).map((segment) => ({ lesson: l, segment })))
}
export function activityBars(days: { date: string; minutes: number; attempts: number }[]) {
  return days.map((d) => ({ label: 'SMTWTFS'[new Date(d.date + 'T00:00:00Z').getUTCDay()], minutes: d.minutes, attempts: d.attempts }))
}
```

`frontend/src/pages/Review.tsx`:
```tsx
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api } from '../api/client'
import type { LessonDetail } from '../api/types'
import Shell from '../components/Shell'
import { flaggedFirst } from '../lib/stats'
import { exportToAnki } from '../anki/export'
import { useSettings } from '../store/settings'
export default function Review() {
  const [lessons, setLessons] = useState<LessonDetail[]>([]); const [msg, setMsg] = useState('')
  const { ankiUrl, exportNote } = useSettings()
  useEffect(() => { api.lessons.list().then((ls) => Promise.all(ls.filter((l) => l.status === 'ready').map((l) => api.lessons.get(l.id)))).then(setLessons) }, [])
  const rows = flaggedFirst(lessons)
  async function sendAll() {
    if (!exportNote) { setMsg('Configure the export note type in Settings'); return }
    let n = 0; for (const r of rows) { try { await exportToAnki(r.segment, ankiUrl, exportNote); n++ } catch (e) { setMsg((e as Error).message) } }
    setMsg(`${n} sent to Anki`)
  }
  return (
    <Shell><div className="max-w-4xl mx-auto p-6 space-y-3">
      <div className="flex justify-between items-center"><h1 className="text-fghi">Review · {rows.length}</h1><button className="btn" onClick={sendAll} disabled={!rows.length}>A → Anki all</button></div>
      {msg && <p className="text-sm text-fgdim">{msg}</p>}
      {rows.map((r) => (
        <div key={r.segment.id} className="flex items-center gap-3 border-b border-line py-2 text-sm">
          <span className="text-fgdim w-32 truncate">{r.lesson.title}</span><span className="font-hanzi flex-1">{r.segment.text}</span>
          <span className="text-fgdim">{r.segment.difficulty_flag ? '⚑' : ''} {r.segment.last_score != null ? Math.round(r.segment.last_score * 100) : ''}</span>
          <Link className="btn" to={`/practice/${r.lesson.id}?seg=${r.segment.idx}`}>Practise</Link>
        </div>))}
    </div></Shell>
  )
}
```

`frontend/src/pages/Stats.tsx`: Shell with four `<section>`s; Activity renders `activityBars(await api.stats.activity(30))` as an inline SVG bar chart (minutes as bar height, attempts as a label under the bar, weekday letters on the axis, colours from the theme per the dataviz skill); the other three sections fetch their endpoints and render tables or the empty-state text `No scores yet — tone scoring arrives in Phase 2.`

In `Practice.tsx`, read `new URLSearchParams(location.search).get('seg')` after the lesson loads and call `st.setIdx(Number(seg))` when present.

Routes `/review`, `/stats` in `App.tsx`.

- [ ] **Step 4: Production build served by the backend**

```bash
cd frontend && npm run build && cd ../backend && uv run uvicorn shadow.main:app --host 127.0.0.1 --port 8000
```
Open `http://127.0.0.1:8000/library`. Expected: the built app loads from the backend and API calls work (same origin).

- [ ] **Step 5: Acceptance checklist**

`docs/phase1-acceptance.md`:
```markdown
# Phase 1 acceptance (manual, Brave on Windows, backend in WSL)

- [ ] Upload a 5–10 min Mandarin video: tile shows stages normalise → transcribe → rectify → align → enrich; lesson ready with 6–25-char sentences; clips start/end cleanly.
- [ ] Upload the same video with its .srt: sentences follow the subtitles.
- [ ] Anki import: Settings → Connect → add query → Library → ⟳: one lesson per source video; re-import adds only new notes.
- [ ] Yomitan: with pinyin ON, hovering 今天 shows the CC-CEDICT entry for the two-character word, not 今 alone; same with pinyin OFF.
- [ ] Echo: Space / Enter / silence stop / back-to-back playback / You track waveform and cells.
- [ ] Chorus: 5 passes, last pass recorded, one attempt with mode chorus.
- [ ] Flow (after): continuous, dots fill in, summary with ▶ ref+you per line; stopping mid-run keeps finished lines.
- [ ] Flow (along) with headphones: recordings contain only your voice.
- [ ] Guided: listen → whisper (text visible) → record (text hidden) → next.
- [ ] Toggles T/P/E persist per lesson after reload; text hides while recording; drawer collapses with L.
- [ ] Timer turns amber at 20:00; "move on" hint after 4 attempts.
- [ ] Edit text → cells and clip update; split and merge; flag ⚑ shows in drawer and Review.
- [ ] A → Anki creates a note with playable mp3; Review → "A → Anki all".
- [ ] Stats → Activity shows today's minutes and attempts.
- [ ] `curl localhost:8000/health` shows device cuda and the loaded models after first use.
```

- [ ] **Step 6: Run everything and commit**

```bash
cd ~/shadow-speech && make test && git add -A && git commit -m "feat(frontend): review and stats pages, production build, acceptance checklist"
```

---

## Self-review notes

- Spec coverage (Phase 1 frontend): §6 modes → Tasks 9–10; §6.1 recording → Task 7; §7.1 stage + drawer → Tasks 9, 11; §7.2 two-track unscored state → Task 8 (score header placeholder, cells neutral); §7.3 Flow view + summary → Task 10; §7.4 Library → Task 4; §7.5 Stats three grains (Phase 1 empty states) → Task 12; §7.6 theme → Task 1; §7.7 Yomitan → Task 5; §8.1 import → Tasks 2–4; §8.2 export → Tasks 11–12. Not in Phase 1 by design: pitch lines, cell colours, score chips (Phase 2), suspect borders (Phase 3), YouTube and asbplayer proxy (Phase 4).
- Type consistency: `Word.syllables` matches the backend plan's `words_json` after its Task 10 edit; `AnkiNotePayload` matches `AnkiNoteIn`; `Mode` strings match the backend's accepted set; `FlowResult`/`ActualPlay` used only within Task 10 and `FlowSummary`.
- Review Focus tests: (1) Task 9 `record failure returns to idle`; (2) Task 10 `skips unfinished`; (3) Task 5 `survives missing words`; (4) Task 2 `skips notes without audio`; (5) Task 9 `ignores typing targets`.
