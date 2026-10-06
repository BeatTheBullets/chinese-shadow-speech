import type { Segment } from '../api/types'
export function dotClass(seg: Segment, pending: boolean): string {
  if (pending) return 'border border-dashed border-fgdim'
  if (seg.last_score == null) return 'bg-line'
  return seg.last_score >= 0.8 ? 'bg-ok' : seg.last_score >= 0.6 ? 'bg-warn' : 'bg-bad'
}
export default function Drawer({ segments, idx, open, pendingIds, onJump, onToggle }: { segments: Segment[]; idx: number; open: boolean; pendingIds: Set<number>; onJump: (i: number) => void; onToggle: () => void }) {
  if (!open) return <button className="w-6 border-l border-line text-fgdim text-xs" onClick={onToggle} title="Open lesson list (L)">▸</button>
  return (
    <aside className="w-80 border-l border-line overflow-y-auto">
      <div className="flex justify-between px-3 py-2 text-[10px] uppercase tracking-widest text-fgdim"><span>Lesson</span><button onClick={onToggle}>◂ L</button></div>
      {segments.map((s, i) => (
        <button key={s.id} onClick={() => onJump(i)} title={`${s.text}${s.last_score != null ? `\nlast ${Math.round(s.last_score * 100)} · best ${Math.round((s.best_score ?? 0) * 100)}` : ''}`}
          className={`w-full flex items-center gap-2 px-3 py-1 text-left text-sm ${i === idx ? 'bg-[#1c2a3a] text-fghi' : 'text-fgdim'}`}>
          <span className="w-5 text-right text-[10px]">{s.idx + 1}</span>
          <span className={`w-2 h-2 rounded-full flex-none ${dotClass(s, pendingIds.has(s.id))}`} />
          <span className="truncate font-hanzi">{s.text}</span>
          {s.difficulty_flag && <span className="text-warn">⚑</span>}
        </button>))}
    </aside>
  )
}
