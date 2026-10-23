import type { Score } from '../api/types'

export const scoreText = (v: number | null): string => (v == null ? '—' : String(Math.round(v * 100)))

export function changeText(s: Score): string {
  if (s.last7 == null || s.prev7 == null) return '—'
  const d = Math.round((s.last7 - s.prev7) * 100)
  return d > 0 ? `▲ ${d}` : d < 0 ? `▼ ${Math.abs(d)}` : '±0'
}

export const HOW: Record<'characters' | 'tones' | 'sounds', string> = {
  characters: "Share of your takes where both tone and sound were right, averaged over the characters you've practised (≥ 3 times, last 30 days).",
  tones: 'Your average tone score over all scored syllables in the last 30 days (neutral tone left out).',
  sounds: 'Share of syllables said right among the hard sounds — zh/ch/sh vs z/c/s, r vs l, ü vs u, -n vs -ng and the vowel pairs ou/uo, an/en, ang/eng; last 30 days. f/h is left out.',
}

export const UNIT = { characters: 'characters', tones: 'syllables', sounds: 'syllables' } as const
