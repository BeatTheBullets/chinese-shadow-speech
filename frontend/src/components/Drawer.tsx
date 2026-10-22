import { useEffect, useState } from 'react'
import type { Passage, Segment } from '../api/types'
import { groupByPassage, passageDone } from '../lib/passages'
import Button from '../ui/Button'

export function dotClass(seg: Segment, pending: boolean): string {
  if (pending) return 'border border-dashed border-fgdim'
  if (seg.last_score == null) return 'bg-line'
  return seg.last_score >= 0.8 ? 'bg-ok' : seg.last_score >= 0.6 ? 'bg-warn' : 'bg-bad'
}
interface Props {
  segments: Segment[]; idx: number; open: boolean; pendingIds: Set<number>; onJump: (i: number) => void; onClose: () => void
  onEdit: (i: number) => void; onSplit: (i: number) => void; onMerge: (i: number) => void
  passages?: Passage[]; practised?: readonly number[]
}
// The lesson's sentences, grouped under passage headers (✓ when every sentence of the passage has an attempt).
// A panel opened from the navigator (rendered inside its pill's wrapper, so it sits just above it) over a dimming scrim.
// Non-modal like the Sound pop-up (role="group", never "dialog"): Space/Enter/arrows keep working for the page; Esc closes.
export default function Drawer({ segments, idx, open, pendingIds, onJump, onClose, onEdit, onSplit, onMerge, passages = [], practised = [] }: Props) {
  const [menu, setMenu] = useState<number | null>(null) // the row whose ⋯ menu is open
  useEffect(() => {
    if (!open) return
    // One Esc closes only the topmost thing: a dialog/help overlay or the Sound pop-up is still in the DOM while its own
    // handler runs (state updates are async), so the drawer leaves the key to it.
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !document.querySelector('[role="dialog"], [data-popover-open]')) onClose() }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [open, onClose])
  if (!open) return null
  const pick = (fn: (i: number) => void, i: number) => () => { setMenu(null); fn(i) }
  const item = 'px-2 py-0.5 rounded-lg border border-line bg-card hover:text-fg disabled:opacity-40'
  return (<>
    <div data-testid="drawer-scrim" className="fixed inset-0 z-30 bg-bg/60" onClick={onClose} />
    <aside data-testid="lesson-drawer" role="group" aria-label="Lesson list" className="absolute bottom-full left-0 mb-2 z-40 w-[360px] max-w-[calc(100vw-1.5rem)] max-h-[70vh] overflow-y-auto rounded-xl border border-line bg-panel shadow-lg">
      {/* closing it: a labelled button with its key as the hint, never a key face (spec §2) */}
      <div className="flex items-center justify-between px-3 py-2">
        <span className="text-[10px] uppercase tracking-widest text-fgdim">Lesson</span>
        <Button label="Lesson list" keyHint="L" variant="ghost" ariaLabel="Close lesson list (L)" onClick={onClose} />
      </div>
      {groupByPassage(segments, passages).map((g, gi) => (
        <div key={g.passage ? `p${g.passage.idx}` : `loose${gi}`} data-testid={g.passage ? `passage-${g.passage.idx}` : 'passage-none'}>
          {g.passage && (
            <div data-testid="passage-header" className="flex justify-between gap-2 px-3 pt-3 pb-1 text-[10px] uppercase tracking-widest text-fgdim">
              <span className="truncate">{g.passage.title}</span>
              {passageDone(g.passage, segments, practised) && <span className="text-ok" aria-label="passage done">✓</span>}
            </div>)}
          {g.rows.map(({ i, seg: s }) => (
            <div key={s.id}>
              <div className={`flex items-center text-sm ${i === idx ? 'bg-card text-fg shadow-[inset_2px_0_0_theme(colors.accent)]' : 'text-fgdim hover:text-fg'}`}>
                <button onClick={() => onJump(i)} title={`${s.text}${s.last_score != null ? `\nlast ${Math.round(s.last_score * 100)} · best ${Math.round((s.best_score ?? 0) * 100)}` : ''}`}
                  className="flex-1 min-w-0 flex items-center gap-2 pl-3 py-1 text-left">
                  <span className="w-5 text-right text-[10px]">{s.idx + 1}</span>
                  <span className={`w-2 h-2 rounded-full flex-none ${dotClass(s, pendingIds.has(s.id))}`} />
                  <span className="truncate font-hanzi">{s.text}</span>
                  {s.difficulty_flag && <span className="text-warn">⚑</span>}
                </button>
                <button className="px-2 py-1 text-fgdim hover:text-fg" aria-label={`Actions for sentence ${i + 1}`} aria-haspopup="menu" aria-expanded={menu === i}
                  onClick={() => setMenu(menu === i ? null : i)}>⋯</button>
              </div>
              {menu === i && (
                <div role="menu" className="flex gap-1 px-3 py-1 text-xs text-fgdim">
                  <button role="menuitem" className={item} onClick={pick(onEdit, i)}>Edit text</button>
                  <button role="menuitem" className={item} onClick={pick(onSplit, i)}>Split here</button>
                  <button role="menuitem" className={item} onClick={pick(onMerge, i)} disabled={i === segments.length - 1}>Merge with next</button>
                </div>)}
            </div>))}
        </div>))}
    </aside>
  </>)
}
