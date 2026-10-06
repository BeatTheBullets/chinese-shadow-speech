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
