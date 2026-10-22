import { useEffect, useState } from 'react'

const frame = (cb: () => void): number => (typeof requestAnimationFrame === 'function' ? requestAnimationFrame(cb) : window.setTimeout(cb, 16))
const cancelFrame = (id: number) => { if (typeof cancelAnimationFrame === 'function') cancelAnimationFrame(id); else window.clearTimeout(id) }

// performance.now() in seconds, refreshed every animation frame while `active` (ghost wipe, turn bar, the take timer).
export function useNow(active: boolean): number {
  const [now, setNow] = useState(() => performance.now() / 1000)
  useEffect(() => {
    if (!active) return
    let id = 0
    const tick = () => { setNow(performance.now() / 1000); id = frame(tick) }
    id = frame(tick)
    return () => cancelFrame(id)
  }, [active])
  return now
}
