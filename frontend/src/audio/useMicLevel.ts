import { useEffect, useState } from 'react'
import type { Mic } from './useMic'

export const METER_MS = 50 // ~20 updates per second (addendum §6.3)

// The microphone level while it is open, else null. Re-renders only when the value changes.
export function useMicLevel(mic: Pick<Mic, 'level'>): number | null {
  const [level, setLevel] = useState<number | null>(null)
  useEffect(() => {
    const t = window.setInterval(() => { const v = mic.level(); setLevel((p) => (p === v ? p : v)) }, METER_MS)
    return () => window.clearInterval(t)
  }, [mic])
  return level
}
