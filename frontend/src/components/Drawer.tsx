import { useState } from 'react'
import type { Passage, Segment } from '../api/types'
import { groupByPassage, passageDone } from '../lib/passages'
export function dotClass(seg: Segment, pending: boolean): string {
  if (pending) return 'border border-dashed border-fgdim'
  if (seg.last_score == null) return 'bg-line'
  return seg.last_score >= 0.8 ? 'bg-ok' : seg.last_score >= 0.6 ? 'bg-warn' : 'bg-bad'
}
interface Props {
  segments: Segment[]; idx: number; open: boolean; pendingIds: Set<number>; onJump: (i: number) => void; onToggle: () => void
  onEdit: (i: number) => void; onSplit: (i: number) => void; onMerge: (i: number) => void
  passages?: Passage[]; practised?: readonly number[]
}
// The lesson's sentences, grouped under passage headers (✓ when every sentence of the passage has an attempt).
export default function Drawer({ segments, idx, open, pendingIds, onJump, onToggle, onEdit, onSplit, onMerge, passages = [], practised = [] }: Props) {
  const [menu, setMenu] = useState<number | null>(null) // the row whose ⋯ menu is open
  if (!open) return <button className="w-6 border-l border-line text-fgdim text-xs" onClick={onToggle} title="Open lesson list (L)">▸</button>
  const pick = (fn: (i: number) => void, i: number) => () => { setMenu(null); fn(i) }
  const item = 'px-2 py-0.5 rounded bg-card hover:text-fg disabled:opacity-40'
  return (
    <aside className="w-80 border-l border-line overflow-y-auto">
      <div className="flex justify-between px-3 py-2 text-[10px] uppercase tracking-widest text-fgdim"><span>Lesson</span><button onClick={onToggle}>◂ L</button></div>
      {groupByPassage(segments, passages).map((g, gi) => (
        <div key={g.passage ? `p${g.passage.idx}` : `loose${gi}`} data-testid={g.passage ? `passage-${g.passage.idx}` : 'passage-none'}>
          {g.passage && (
            <div data-testid="passage-header" className="flex justify-between gap-2 px-3 pt-3 pb-1 text-[10px] uppercase tracking-widest text-fgdim">
              <span className="truncate">{g.passage.title}</span>
              {passageDone(g.passage, segments, practised) && <span className="text-ok" aria-label="passage done">✓</span>}
            </div>)}
          {g.rows.map(({ i, seg: s }) => (
            <div key={s.id}>
              <div className={`flex items-center text-sm ${i === idx ? 'bg-card text-fg' : 'text-fgdim'}`}>
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
  )
}
