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
  it('CANCEL returns to idle from every state', () => {
    for (const s of ['idle', 'playing', 'recording', 'uploading', 'playback'] as const) expect(echoReducer(s, 'CANCEL')).toBe('idle')
  })
})
