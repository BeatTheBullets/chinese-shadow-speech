import { create } from 'zustand'
import type { LessonDetail, Mode, Passage, Score, Segment } from '../api/types'
import { defaultTextPrefs, type TextPrefs } from './settings'

export interface LastAttempt { id: number; url: string; duration: number; peaks: Float32Array | null; score?: Score | null }
// A sentence's newest take on the server (from an earlier visit, or uploaded during this one); `url` is its attempt audio.
export interface StoredTake { id: number; url: string; duration: number; score?: Score | null }
export interface PracticeState {
  lesson: LessonDetail | null; idx: number; mode: Mode; sessionId: number | null; rate: number; drawerOpen: boolean
  attemptsThisSegment: number; lastAttempt: LastAttempt | null; textPrefs: TextPrefs; recordingNow: boolean; hint: string
  practised: number[] // sentence ids with an attempt uploaded during this visit
  storedTakes: Record<number, StoredTake> // by sentence id
  setLesson: (l: LessonDetail) => void; setIdx: (i: number) => void; setMode: (m: Mode) => void; setSession: (id: number | null) => void
  setRate: (r: number) => void; toggleDrawer: () => void; bumpAttempts: () => void; setLastAttempt: (a: LastAttempt | null) => void
  setTextPrefs: (p: TextPrefs) => void; setRecording: (b: boolean) => void; setHint: (h: string) => void
  updateSegment: (s: Segment) => void; replaceSegments: (segs: Segment[], passages?: Passage[]) => void; markPractised: (id: number) => void
  setStoredTakes: (t: Record<number, StoredTake>) => void; recordTake: (segmentId: number, t: StoredTake) => void
}

// A recorded take lives in a blob: URL; free it once the take is replaced or dropped.
function release(prev: LastAttempt | null, next: LastAttempt | null) {
  if (prev && prev.url !== next?.url && prev.url.startsWith('blob:')) URL.revokeObjectURL(prev.url)
}

export const usePractice = create<PracticeState>((set) => ({
  lesson: null, idx: 0, mode: 'echo', sessionId: null, rate: 1.0, drawerOpen: true, attemptsThisSegment: 0, lastAttempt: null,
  textPrefs: defaultTextPrefs, recordingNow: false, hint: '', practised: [], storedTakes: {},
  setLesson: (lesson) => set((s) => { release(s.lastAttempt, null); return { lesson, idx: 0, attemptsThisSegment: 0, lastAttempt: null, hint: '', practised: [], storedTakes: {} } }),
  setIdx: (idx) => set((s) => { release(s.lastAttempt, null); return { idx, attemptsThisSegment: 0, lastAttempt: null, hint: '' } }),
  setMode: (mode) => set({ mode }), setSession: (sessionId) => set({ sessionId }), setRate: (rate) => set({ rate }),
  toggleDrawer: () => set((s) => ({ drawerOpen: !s.drawerOpen })), bumpAttempts: () => set((s) => ({ attemptsThisSegment: s.attemptsThisSegment + 1 })),
  setLastAttempt: (lastAttempt) => set((s) => { release(s.lastAttempt, lastAttempt); return { lastAttempt } }),
  setTextPrefs: (textPrefs) => set({ textPrefs }), setRecording: (recordingNow) => set({ recordingNow }), setHint: (hint) => set({ hint }),
  updateSegment: (seg) => set((s) => s.lesson ? { lesson: { ...s.lesson, segments: s.lesson.segments.map((x) => (x.id === seg.id ? seg : x)) } } : {}),
  replaceSegments: (segments, passages) => set((s) => (s.lesson ? { lesson: { ...s.lesson, segments, ...(passages ? { passages } : {}) } } : {})),
  markPractised: (id) => set((s) => (s.practised.includes(id) ? {} : { practised: [...s.practised, id] })),
  // Merged in, the higher attempt id winning per sentence: an answer that was in flight never undoes a newer upload.
  setStoredTakes: (takes) => set((s) => {
    const storedTakes = { ...s.storedTakes }
    for (const [id, t] of Object.entries(takes)) {
      const cur = storedTakes[Number(id)]
      if (!cur || cur.id <= t.id) storedTakes[Number(id)] = t
    }
    return { storedTakes }
  }),
  recordTake: (segmentId, t) => set((s) => ({ storedTakes: { ...s.storedTakes, [segmentId]: t } })),
}))
export const currentSegment = (s: PracticeState): Segment | null => s.lesson?.segments[s.idx] ?? null
// The take R replays and the You track shows: this visit's last take of the current sentence (also while its upload
// is pending), unless the sentence's stored take is newer (attempt ids only grow), e.g. from a Flow run since.
export function currentTake(s: PracticeState): LastAttempt | StoredTake | null {
  const seg = currentSegment(s), last = s.lastAttempt
  const stored = seg ? s.storedTakes[seg.id] : undefined
  if (last && (last.id === 0 || !stored || last.id >= stored.id)) return last
  return stored ?? null
}
