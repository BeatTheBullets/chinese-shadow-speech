import { cellClass, type Cell } from '../lib/cells'
import { cellTitle, pct } from '../lib/score'

function youMark(c: Cell): string {
  if (c.status === 'unvoiced') return '∅'
  if (c.status === 'missing' || c.score == null) return '–'
  return pct(c.score)
}
// Your verdict cells, one per syllable under your track (the Echo review's only cell row). Every cell is the same
// fixed size and its lines cannot wrap (they truncate), and the row aligns cells at the top, so a longer label can
// never make one cell taller than its neighbours and lift it out of line. HeardRow's slots share this width and gap.
// highlight: cell indexes to outline (a drill's target syllables).
const CELL_SIZE = 'w-12 h-14'  // HeardRow's slots are w-12 too
export default function CellRow({ cells, onCellClick, highlight }: { cells: Cell[]; onCellClick?: (i: number) => void; highlight?: number[] }) {
  return (
    <div className="flex flex-wrap items-start gap-1 mt-2 justify-center">
      {cells.map((c, i) => (
        <button key={i} title={cellTitle(c)} onClick={() => onCellClick?.(i)}
          className={`${CELL_SIZE} shrink-0 overflow-hidden whitespace-nowrap rounded border px-0.5 flex flex-col items-center justify-center ${cellClass(c)}${highlight?.includes(i) ? ' ring-2 ring-accent' : ''}`}>
          <span className="block w-full truncate font-hanzi text-fg text-base leading-tight">{c.ch}</span>
          <span className="block w-full truncate text-[10px] leading-tight text-ref">{c.status === 'wrong' && c.target != null && c.heard != null ? `${c.target}→${c.heard}` : `${c.tone >= 0 ? c.tone : ''}`}</span>
          <span className="block w-full truncate text-[9px] leading-tight text-fgdim">{youMark(c)}</span>
        </button>))}
    </div>
  )
}
