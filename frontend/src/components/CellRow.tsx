import { cellClass, type Cell } from '../lib/cells'
import { cellTitle, pct } from '../lib/score'

function youMark(c: Cell): string {
  if (c.status === 'unvoiced') return '∅'
  if (c.status === 'missing' || c.score == null) return '–'
  return pct(c.score)
}
export default function CellRow({ cells, variant, onCellClick }: { cells: Cell[]; variant: 'ref' | 'you'; onCellClick?: (i: number) => void }) {
  return (
    <div className="flex flex-wrap gap-1 mt-2 justify-center">
      {cells.map((c, i) => (
        <button key={i} title={variant === 'you' ? cellTitle(c) : c.pinyin} onClick={() => onCellClick?.(i)}
          className={`w-10 max-w-[56px] rounded border px-1 py-1 text-center ${cellClass(c)}`}>
          <span className="block font-hanzi text-fghi text-sm leading-tight">{c.ch}</span>
          <span className="block text-[10px] text-ref">{variant === 'ref' ? `${c.pinyin} ${c.tone >= 0 ? c.tone : ''}`
            : c.status === 'wrong' && c.target != null && c.heard != null ? `${c.target}→${c.heard}` : `${c.tone >= 0 ? c.tone : ''}`}</span>
          {variant === 'you' && <span className="block text-[9px] text-fgdim">{youMark(c)}</span>}
        </button>))}
    </div>
  )
}
