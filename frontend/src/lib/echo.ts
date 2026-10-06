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
