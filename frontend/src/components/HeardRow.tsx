import type { Cell } from '../lib/cells'

// What was heard where a sound was wrong (Phase 3a spec §1.1), one slot per You cell at CellRow's fixed width and gap so
// it lines up under them, the expected pinyin in the slot's tooltip; empty slots keep the rest aligned. The label sits
// on its own line above the slots so it can never cover a slip. Nothing at all when no sound slipped.
export default function HeardRow({ cells }: { cells: Cell[] }) {
  if (!cells.some((c) => c.heardSound)) return null
  return (
    <div className="mt-1">
      <div className="text-[9px] uppercase tracking-widest text-sound">HEARD</div>
      <div className="flex flex-wrap items-start gap-1 justify-center">
        {cells.map((c, i) => (
          <div key={i} data-slot title={c.heardSound ? `heard ${c.heardSound} instead of ${c.pinyin}` : undefined}
            className={`w-12 shrink-0 h-[22px] overflow-hidden whitespace-nowrap rounded px-0.5 py-0.5 text-center${c.heardSound ? ' border border-dashed border-sound' : ''}`}>
            {c.heardSound && <span className="text-[11px] text-sound font-semibold">{c.heardSound}</span>}
          </div>))}
      </div>
    </div>
  )
}
