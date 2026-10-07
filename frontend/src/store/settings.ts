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
  referenceVolume: number   // 0–1: every reference playback and your own takes (addendum §7)
  guideLevel: number        // 0–1 of the reference volume while speaking along (Chorus, Flow along)
  helpSeen: boolean         // the practice help overlay has opened once
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
  referenceVolume: 1, guideLevel: 0.5, helpSeen: false,
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
