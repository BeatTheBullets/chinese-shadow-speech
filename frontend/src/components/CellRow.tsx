import { cellClass, type Cell } from '../lib/cells'
import { cellTitle, pct } from '../lib/score'

function youMark(c: Cell): string {
  if (c.status === 'unvoiced') return '∅'
  if (c.status === 'missing' || c.score == null) return '–'
  return pct(c.score)
}
// highlight: cell indexes to outline (a drill's target syllables). soundMarks: cells to ring in purple (a heard wrong sound; purple means sound only).
export default function CellRow({ cells, variant, onCellClick, highlight, soundMarks }: { cells: Cell[]; variant: 'ref' | 'you'; onCellClick?: (i: number) => void; highlight?: number[]; soundMarks?: number[] }) {
  // One ring per cell: the purple sound ring wins over a drill's accent outline (a sound drill's targets are the marked cells).
  const ring = (i: number) => (soundMarks?.includes(i) ? ' ring-2 ring-sound' : highlight?.includes(i) ? ' ring-2 ring-accent' : '')
  return (
    <div className="flex flex-wrap gap-1 mt-2 justify-center">
      {cells.map((c, i) => (
        <button key={i} title={variant === 'you' ? cellTitle(c) : c.pinyin} onClick={() => onCellClick?.(i)}
          className={`w-10 max-w-[56px] rounded border px-1 py-1 text-center ${cellClass(c)}${ring(i)}`}>
          <span className="block font-hanzi text-fg text-sm leading-tight">{c.ch}</span>
          <span className="block text-[10px] text-ref">{variant === 'ref' ? `${c.pinyin} ${c.tone >= 0 ? c.tone : ''}`
            : c.status === 'wrong' && c.target != null && c.heard != null ? `${c.target}→${c.heard}` : `${c.tone >= 0 ? c.tone : ''}`}</span>
          {variant === 'you' && <span className="block text-[9px] text-fgdim">{youMark(c)}</span>}
        </button>))}
    </div>
  )
}
