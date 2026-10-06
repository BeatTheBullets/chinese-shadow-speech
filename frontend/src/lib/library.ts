import type { Lesson } from '../api/types'

export function groupBySpeaker(lessons: Lesson[], languageParent: string | null) {
  const map = new Map<string, Lesson[]>()
  for (const l of lessons) {
    const k = l.speaker?.trim() || 'Unsorted'
    map.set(k, [...(map.get(k) ?? []), l])
  }
  const groups = [...map.entries()].map(([speaker, ls]) => ({
    speaker, pinned: !!languageParent && speaker === languageParent,
    lessons: [...ls].sort((a, b) => b.created_at.localeCompare(a.created_at)),
  }))
  return groups.sort((a, b) => Number(b.pinned) - Number(a.pinned) || b.lessons[0].created_at.localeCompare(a.lessons[0].created_at))
}
