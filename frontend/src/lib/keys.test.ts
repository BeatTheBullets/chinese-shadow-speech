import { describe, it, expect } from 'vitest'
import { shouldHandleKey, KEYMAP, actionForKey } from './keys'
describe('keys', () => {
  it('ignores typing targets', () => {
    const input = document.createElement('input'); const div = document.createElement('div'); const ce = document.createElement('div'); ce.setAttribute('contenteditable', 'true')
    expect(shouldHandleKey(input)).toBe(false); expect(shouldHandleKey(div)).toBe(true); expect(shouldHandleKey(ce)).toBe(false); expect(shouldHandleKey(null)).toBe(true)
  })
  it('ignores textarea, select and children of a contenteditable', () => {
    const ce = document.createElement('div'); ce.setAttribute('contenteditable', 'true')
    const child = document.createElement('span'); ce.appendChild(child)
    expect(shouldHandleKey(document.createElement('textarea'))).toBe(false)
    expect(shouldHandleKey(document.createElement('select'))).toBe(false)
    expect(shouldHandleKey(child)).toBe(false)
  })
  it('maps keys', () => { expect(KEYMAP[' ']).toBe('play'); expect(KEYMAP['Enter']).toBe('record'); expect(KEYMAP['l']).toBe('toggleDrawer') })
  it('actionForKey maps plain keys outside typing targets', () => {
    const div = document.createElement('div')
    expect(actionForKey({ key: 'Enter', target: div, ctrlKey: false, metaKey: false, altKey: false, repeat: false })).toBe('record')
    expect(actionForKey({ key: 'q', target: div, ctrlKey: false, metaKey: false, altKey: false, repeat: false })).toBeNull()
    expect(actionForKey({ key: 'Enter', target: document.createElement('input'), ctrlKey: false, metaKey: false, altKey: false, repeat: false })).toBeNull()
  })
  it('actionForKey leaves browser shortcuts and auto-repeat alone', () => {
    const base = { target: null, ctrlKey: false, metaKey: false, altKey: false, repeat: false }
    expect(actionForKey({ ...base, key: 'r', ctrlKey: true })).toBeNull()   // reload
    expect(actionForKey({ ...base, key: 'c', metaKey: true })).toBeNull()   // copy
    expect(actionForKey({ ...base, key: 'ArrowLeft', altKey: true })).toBeNull() // history back
    expect(actionForKey({ ...base, key: ' ', repeat: true })).toBeNull()
  })
  it('ignores keys inside an open dialog, buttons included', () => {
    const dlg = document.createElement('div'); dlg.setAttribute('role', 'dialog')
    const btn = document.createElement('button'); dlg.appendChild(btn)
    expect(shouldHandleKey(dlg)).toBe(false)
    expect(shouldHandleKey(btn)).toBe(false)
    const base = { target: btn, ctrlKey: false, metaKey: false, altKey: false, repeat: false }
    expect(actionForKey({ ...base, key: ' ' })).toBeNull()
    expect(actionForKey({ ...base, key: 'ArrowRight' })).toBeNull()
  })
})
