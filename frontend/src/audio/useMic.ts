import { useEffect, useRef, useState } from 'react'
import { rms } from './pcm'
import { Recorder } from './recorder'

export interface Mic {
  // Opens the mic and starts capturing. Resolves to null if abandon() ran meanwhile; a recorder that starts after
  // that is stopped at once so the mic is not left open. Throws a readable error.
  open(): Promise<Recorder | null>
  // Drops the capture in flight, including one still waiting at the permission prompt.
  abandon(): void
  // Ends the capture to keep it: the mic closes and the recorder (for its clock) comes back with every sample.
  finish(): { rec: Recorder; samples: Float32Array } | null
  capturing(): boolean
  // The recording clock (AudioContext.currentTime), the time base of Recorder.startTime.
  now(): number
  // RMS of the last 2048 samples while capturing (the level meter, addendum §6.3), else null.
  level(): number | null
}

// The page's microphone: one AudioContext and Recorder, created on first use, closed on unmount.
export function useMic(): Mic {
  const ctxRef = useRef<AudioContext | null>(null)
  const recRef = useRef<Recorder | null>(null)
  const gen = useRef(0)                                   // bumping it abandons the capture in flight
  const capturing = useRef(false)                         // the mic is open and samples are arriving
  const pendingStart = useRef<Promise<void> | null>(null) // a Recorder.start() still waiting (e.g. on the permission prompt)
  const [mic] = useState<Mic>(() => ({
    async open() {
      const mine = ++gen.current
      // Recorder.start() is not re-entrant: let an abandoned start (still at the permission prompt) settle first.
      while (pendingStart.current) await pendingStart.current
      if (mine !== gen.current) return null
      ctxRef.current ??= new AudioContext()
      recRef.current ??= new Recorder(ctxRef.current)
      const rec = recRef.current
      const starting = rec.start()
      const settled = starting.then(() => {}, () => {})
      pendingStart.current = settled
      try { await starting } catch (e) { if (mine !== gen.current) return null; throw e } finally { if (pendingStart.current === settled) pendingStart.current = null }
      if (mine !== gen.current) { rec.stop(); return null }
      capturing.current = true
      return rec
    },
    abandon() {
      gen.current++
      if (capturing.current) { recRef.current?.stop(); capturing.current = false }
    },
    finish() {
      const rec = recRef.current, was = capturing.current
      capturing.current = false
      return rec && was ? { rec, samples: rec.stop() } : null
    },
    capturing: () => capturing.current,
    now: () => ctxRef.current?.currentTime ?? 0,
    level: () => (capturing.current && recRef.current ? rms(recRef.current.tail(2048)) : null),
  }))
  useEffect(() => () => {
    mic.abandon()
    ctxRef.current?.close().catch(() => {})
    ctxRef.current = null; recRef.current = null
  }, [mic])
  return mic
}
