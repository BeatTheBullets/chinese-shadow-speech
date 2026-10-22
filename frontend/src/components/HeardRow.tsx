import type { Cell } from '../lib/cells'

// What was heard where a sound was wrong (Phase 3a spec §1.1), one slot per You cell at CellRow's width and gap so it
// lines up under them; empty slots keep the rest aligned. Nothing at all when no sound slipped.
export default function HeardRow({ cells }: { cells: Cell[] }) {
  if (!cells.some((c) => c.heardSound)) return null
  return (
    <div className="relative flex flex-wrap gap-1 mt-1 justify-center">
      <span className="absolute left-0 top-1 text-[9px] uppercase tracking-widest text-sound">HEARD</span>
      {cells.map((c, i) => (
        <div key={i} data-slot title={c.heardSound ? `heard ${c.heardSound} instead of ${c.pinyin}` : undefined}
          className={`w-10 max-w-[56px] min-h-[22px] rounded px-1 py-0.5 text-center${c.heardSound ? ' border border-dashed border-sound' : ''}`}>
          {c.heardSound && <span className="text-[11px] text-sound font-semibold">{c.heardSound}</span>}
        </div>))}
    </div>
  )
}
