import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { FieldMapping } from '../anki/import'

export interface ImportQuery { name: string; query: string; mapping: FieldMapping }
export interface ExportNote { deckName: string; modelName: string; fields: { sentence: string; pinyin?: string; translation?: string; audio: string; source?: string; link?: string } }
export interface TextPrefs { hanzi: boolean; pinyin: boolean; translation: boolean }
export interface PracticePrefs { hideTextWhileRecording: boolean; flowGapFactor: number; moveOnAfter: number; defaultRate: number }

interface SettingsState {
  ankiUrl: string
  importQueries: ImportQuery[]
  exportNote: ExportNote | null
  languageParent: string | null
  practice: PracticePrefs
  textPrefs: Record<string, TextPrefs>
  referenceVolume: number   // 0–1: every reference playback and your own takes (addendum §7)
  guideLevel: number        // 0–1 of the reference volume while speaking along (Flow along)
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
  practice: { hideTextWhileRecording: true, flowGapFactor: 1.1, moveOnAfter: 4, defaultRate: 1.0 },
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
}), {
  name: 'shadow.settings',
  // Version 1 dropped Chorus (app style spec §4): a stored practice blob keeps only the keys PracticePrefs still has
  // (an old chorusPasses goes), and any it lacks come from the defaults. The rest of the stored state is kept as is.
  version: 1,
  migrate: (persisted) => {
    const s = (persisted ?? {}) as Partial<SettingsState>
    if (!s.practice || typeof s.practice !== 'object') return s as SettingsState
    const known = Object.keys(defaults.practice) as (keyof PracticePrefs)[]
    const old = s.practice as unknown as Record<string, unknown>
    const practice = Object.fromEntries(known.filter((k) => k in old).map((k) => [k, old[k]]))
    return { ...s, practice: { ...defaults.practice, ...practice } } as SettingsState
  },
}))

export const defaultTextPrefs: TextPrefs = { hanzi: true, pinyin: true, translation: false }
