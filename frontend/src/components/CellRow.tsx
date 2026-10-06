import { cellClass, type Cell } from '../lib/cells'
export default function CellRow({ cells, variant, onCellClick }: { cells: Cell[]; variant: 'ref' | 'you'; onCellClick?: (i: number) => void }) {
  return (
    <div className="flex flex-wrap gap-1 mt-2 justify-center">
      {cells.map((c, i) => (
        <button key={i} title={c.pinyin} onClick={() => onCellClick?.(i)}
          className={`w-10 max-w-[56px] rounded border px-1 py-1 text-center ${cellClass(c)}`}>
          <span className="block font-hanzi text-fghi text-sm leading-tight">{c.ch}</span>
          <span className="block text-[10px] text-ref">{variant === 'ref' ? `${c.pinyin} ${c.tone >= 0 ? c.tone : ''}` : `${c.tone >= 0 ? c.tone : ''}`}</span>
          {variant === 'you' && <span className="block text-[9px] text-fgdim">{c.score != null ? Math.round(c.score * 100) : c.status === 'unvoiced' ? '∅' : '–'}</span>}
        </button>))}
    </div>
  )
}
