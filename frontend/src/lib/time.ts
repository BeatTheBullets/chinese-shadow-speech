// Seconds as mm:ss (minutes keep counting past 59).
export const mmss = (s: number): string => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']
const pad2 = (n: number) => String(n).padStart(2, '0')
// An ISO instant as weekday and 24-hour time in the user's time zone, e.g. "Wed 14:05".
export function weekdayTime(iso: string): string {
  const d = new Date(iso)
  return `${WEEKDAYS[d.getDay()]} ${pad2(d.getHours())}:${pad2(d.getMinutes())}`
}
