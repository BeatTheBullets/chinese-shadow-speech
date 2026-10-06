import type { Lesson, LessonDetail, Segment } from '../api/types'
export function flaggedFirst(lessons: LessonDetail[]): { lesson: Lesson; segment: Segment }[] {
  return [...lessons].sort((a, b) => a.created_at.localeCompare(b.created_at))
    .flatMap((l) => l.segments.filter((s) => s.difficulty_flag || (s.last_score != null && s.last_score < 0.6)).map((segment) => ({ lesson: l, segment })))
}
export function activityBars(days: { date: string; minutes: number; attempts: number }[]) {
  return days.map((d) => ({ label: 'SMTWTFS'[new Date(d.date + 'T00:00:00Z').getUTCDay()], minutes: d.minutes, attempts: d.attempts }))
}
