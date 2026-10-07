import { create } from 'zustand'
import type { LessonDetail, Mode, Passage, Segment } from '../api/types'
import { defaultTextPrefs, type TextPrefs } from './settings'

export interface LastAttempt { id: number; url: string; duration: number; peaks: Float32Array | null }
export interface PracticeState {
  lesson: LessonDetail | null; idx: number; mode: Mode; sessionId: number | null; rate: number; drawerOpen: boolean
  attemptsThisSegment: number; lastAttempt: LastAttempt | null; textPrefs: TextPrefs; recordingNow: boolean; hint: string
  practised: number[] // sentence ids with an attempt uploaded during this visit
  setLesson: (l: LessonDetail) => void; setIdx: (i: number) => void; setMode: (m: Mode) => void; setSession: (id: number | null) => void
  setRate: (r: number) => void; toggleDrawer: () => void; bumpAttempts: () => void; setLastAttempt: (a: LastAttempt | null) => void
  setTextPrefs: (p: TextPrefs) => void; setRecording: (b: boolean) => void; setHint: (h: string) => void
  updateSegment: (s: Segment) => void; replaceSegments: (segs: Segment[], passages?: Passage[]) => void; markPractised: (id: number) => void
}

// A recorded take lives in a blob: URL; free it once the take is replaced or dropped.
function release(prev: LastAttempt | null, next: LastAttempt | null) {
  if (prev && prev.url !== next?.url && prev.url.startsWith('blob:')) URL.revokeObjectURL(prev.url)
}

export const usePractice = create<PracticeState>((set) => ({
  lesson: null, idx: 0, mode: 'echo', sessionId: null, rate: 1.0, drawerOpen: true, attemptsThisSegment: 0, lastAttempt: null,
  textPrefs: defaultTextPrefs, recordingNow: false, hint: '', practised: [],
  setLesson: (lesson) => set((s) => { release(s.lastAttempt, null); return { lesson, idx: 0, attemptsThisSegment: 0, lastAttempt: null, hint: '', practised: [] } }),
  setIdx: (idx) => set((s) => { release(s.lastAttempt, null); return { idx, attemptsThisSegment: 0, lastAttempt: null, hint: '' } }),
  setMode: (mode) => set({ mode }), setSession: (sessionId) => set({ sessionId }), setRate: (rate) => set({ rate }),
  toggleDrawer: () => set((s) => ({ drawerOpen: !s.drawerOpen })), bumpAttempts: () => set((s) => ({ attemptsThisSegment: s.attemptsThisSegment + 1 })),
  setLastAttempt: (lastAttempt) => set((s) => { release(s.lastAttempt, lastAttempt); return { lastAttempt } }),
  setTextPrefs: (textPrefs) => set({ textPrefs }), setRecording: (recordingNow) => set({ recordingNow }), setHint: (hint) => set({ hint }),
  updateSegment: (seg) => set((s) => s.lesson ? { lesson: { ...s.lesson, segments: s.lesson.segments.map((x) => (x.id === seg.id ? seg : x)) } } : {}),
  replaceSegments: (segments, passages) => set((s) => (s.lesson ? { lesson: { ...s.lesson, segments, ...(passages ? { passages } : {}) } } : {})),
  markPractised: (id) => set((s) => (s.practised.includes(id) ? {} : { practised: [...s.practised, id] })),
}))
export const currentSegment = (s: PracticeState): Segment | null => s.lesson?.segments[s.idx] ?? null
