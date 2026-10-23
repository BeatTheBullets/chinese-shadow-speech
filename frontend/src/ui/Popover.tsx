import { useEffect, useRef, type ReactNode } from 'react'

// Non-modal pop-up next to its anchor. Deliberately role="group", not "dialog": the global key handler ignores
// events inside [role="dialog"], and Space/Enter/arrows must keep working while this is open. Only Esc is handled here.
// side: which way it opens, above its anchor (default, for bars at the bottom) or below it (for a line at the top).
export default function Popover({ open, onClose, anchor, children, side = 'above' }: { open: boolean; onClose: () => void; anchor: ReactNode; children: ReactNode; side?: 'above' | 'below' }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    const onDown = (e: PointerEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) onClose() }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onDown)
    return () => { document.removeEventListener('keydown', onKey); document.removeEventListener('pointerdown', onDown) }
  }, [open, onClose])
  // The anchor lives inside the ref'd wrapper so clicking it to toggle is not an "outside" click that re-opens.
  return (
    <div ref={ref} className="relative inline-block">
      {anchor}
      {open && <div role="group" data-popover-open className={`absolute ${side === 'above' ? 'bottom-full right-0 mb-2' : 'top-full left-1/2 -translate-x-1/2 mt-2'} z-20 rounded-xl border border-line bg-panel p-3 text-fg shadow-lg`}>{children}</div>}
    </div>
  )
}
