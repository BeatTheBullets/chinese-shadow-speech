import { describe, it, expect, beforeEach } from 'vitest'
import { useSettings } from './settings'

describe('settings store', () => {
  beforeEach(() => { localStorage.clear(); useSettings.getState().reset() })
  it('has defaults', () => {
    const s = useSettings.getState()
    expect(s.ankiUrl).toBe('http://127.0.0.1:8765')
    expect(s.practice).toEqual({ hideTextWhileRecording: true, flowGapFactor: 1.1, moveOnAfter: 4, defaultRate: 1.0 })
  })
  it('persists queries and text prefs', () => {
    useSettings.getState().addQuery({ name: 'Mining', query: 'deck:Mining', mapping: { sentence: 'Sentence', audio: 'Audio' } })
    useSettings.getState().setTextPrefs(7, { hanzi: true, pinyin: false, translation: false })
    const raw = JSON.parse(localStorage.getItem('shadow.settings')!)
    expect(raw.state.importQueries[0].name).toBe('Mining')
    expect(raw.state.textPrefs['7'].pinyin).toBe(false)
  })
  it('has volume and help defaults and persists them', () => {
    const s = useSettings.getState()
    expect([s.referenceVolume, s.guideLevel, s.helpSeen]).toEqual([1, 0.5, false])
    s.set({ referenceVolume: 0.6, guideLevel: 0.3, helpSeen: true })
    const raw = JSON.parse(localStorage.getItem('shadow.settings')!)
    expect([raw.state.referenceVolume, raw.state.guideLevel, raw.state.helpSeen]).toEqual([0.6, 0.3, true])
  })
  it('settings persisted before the volume keys existed load with the defaults', async () => {
    localStorage.setItem('shadow.settings', JSON.stringify({ state: { ankiUrl: 'http://x:1', textPrefs: {} }, version: 0 }))
    await useSettings.persist.rehydrate()
    const s = useSettings.getState()
    expect(s.ankiUrl).toBe('http://x:1')
    expect([s.referenceVolume, s.guideLevel, s.helpSeen]).toEqual([1, 0.5, false])
  })
  it('settings with a stale chorusPasses still load', async () => {
    localStorage.setItem('shadow.settings', JSON.stringify({ state: { ankiUrl: 'http://x:2',
      practice: { hideTextWhileRecording: false, chorusPasses: 5, flowGapFactor: 1.3, moveOnAfter: 6, defaultRate: 0.8 } }, version: 0 }))
    await expect(useSettings.persist.rehydrate()).resolves.not.toThrow()
    const s = useSettings.getState()
    expect(s.ankiUrl).toBe('http://x:2')
    expect(s.practice.defaultRate).toBe(0.8)
    expect(s.practice).toEqual({ hideTextWhileRecording: false, flowGapFactor: 1.3, moveOnAfter: 6, defaultRate: 0.8 })
    expect(JSON.parse(localStorage.getItem('shadow.settings')!).version).toBe(1)
  })
})
