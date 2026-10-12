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

export const needsPolling = (lessons: Lesson[]) => lessons.some((l) => l.status !== 'ready' && l.status !== 'error')

// The question asked before a lesson is deleted (every status may be deleted, a broken upload included).
export function deleteConfirmText(l: Lesson): string {
  const n = l.segment_count
  const what = n ? `its ${n} sentence${n === 1 ? '' : 's'}, their practice history and audio` : 'its audio'
  const busy = l.status === 'queued' || l.status === 'processing' ? ' It is still processing; that job stops.' : ''
  return `Delete "${l.title}" with ${what}?${busy} This cannot be undone.`
}

// Rebuild text re-transcribes a lesson's own audio: an Anki lesson is cut from its notes' audio (nothing to
// transcribe), and a lesson still processing or broken is not offered it.
export const canRebuild = (l: Lesson) => l.status === 'ready' && l.source_type !== 'anki'

export function rebuildConfirmText(l: Lesson): string {
  return `Rebuild the text of "${l.title}"? This transcribes the lesson's audio again and rebuilds its sentences and clips. ` +
    'It keeps your takes: each moves to the matching sentence (the one at the same time), and the app scores them again.'
}

// The PATCH body for a rename from the two prompts' answers (null = cancelled): only changed fields, trimmed.
// An empty title keeps the old one; an empty speaker is allowed (the lesson moves to Unsorted).
export function renamePatch(l: Lesson, title: string | null, speaker: string | null): { title?: string; speaker?: string } | null {
  if (title == null || speaker == null) return null
  const body: { title?: string; speaker?: string } = {}
  const t = title.trim(), s = speaker.trim()
  if (t && t !== l.title) body.title = t
  if (s !== l.speaker) body.speaker = s
  return Object.keys(body).length ? body : null
}
