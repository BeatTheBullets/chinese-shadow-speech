import { cellClass, type Cell } from '../lib/cells'
import { cellTitle, pct } from '../lib/score'
import { IconMe, IconPlay } from '../ui/icons'

function youMark(c: Cell): string {
  if (c.status === 'unvoiced') return '∅'
  if (c.status === 'missing' || c.score == null) return '–'
  return pct(c.score)
}
// Your verdict cells, one per syllable under your track (the Echo review's only cell row). Every cell is the same
// fixed size and its lines cannot wrap (they truncate), and the row aligns cells at the top, so a longer label can
// never make one cell taller than its neighbours and lift it out of line. HeardRow's slots share this width and gap.
// Each cell: the character, its tone and your score (click: the speaker's syllable, a pause, then yours, onCellClick),
// then two tiny buttons to compare one syllable by ear: ▶ the speaker says it (onSpeaker, in the speaker's colour) and
// your head, you say it (onMe, in yours). A missing or unvoiced syllable, or one not scored yet, has nothing of yours.
// highlight: cell indexes to outline (a drill's target syllables).
const CELL_SIZE = 'w-12 h-16'  // HeardRow's slots are w-12 too; h-16 holds the three lines and the button pair
const PAIR_BTN = 'w-[18px] h-4 rounded flex items-center justify-center bg-bg disabled:opacity-30 [&_svg]:w-3 [&_svg]:h-3'
const hasYours = (c: Cell) => c.status != null && c.status !== 'neutral' && c.status !== 'missing' && c.status !== 'unvoiced'
export default function CellRow({ cells, onCellClick, onSpeaker, onMe, highlight }: {
  cells: Cell[]; onCellClick?: (i: number) => void; onSpeaker?: (i: number) => void; onMe?: (i: number) => void; highlight?: number[]
}) {
  return (
    <div className="flex flex-wrap items-start gap-1 mt-2 justify-center">
      {cells.map((c, i) => (
        <div key={i} data-testid="cell"
          className={`${CELL_SIZE} shrink-0 overflow-hidden whitespace-nowrap rounded border px-0.5 flex flex-col items-center justify-center ${cellClass(c)}${highlight?.includes(i) ? ' ring-2 ring-accent' : ''}`}>
          <button type="button" data-testid="cell-compare" title={`${cellTitle(c)} · click: the speaker, then you`} onClick={() => onCellClick?.(i)}
            className="w-full flex flex-col items-center">
            <span className="block w-full truncate font-hanzi text-fg text-base leading-tight">{c.ch}</span>
            <span className="block w-full truncate text-[10px] leading-tight text-ref">{c.status === 'wrong' && c.target != null && c.heard != null ? `${c.target}→${c.heard}` : `${c.tone >= 0 ? c.tone : ''}`}</span>
            <span className="block w-full truncate text-[9px] leading-tight text-fgdim">{youMark(c)}</span>
          </button>
          <span className="flex gap-1 mt-0.5">
            <button type="button" aria-label={`Speaker says ${c.ch}`} title={`Speaker says ${c.ch}`} onClick={() => onSpeaker?.(i)} className={`${PAIR_BTN} text-ref`}><IconPlay /></button>
            <button type="button" aria-label={`You say ${c.ch}`} title={`You say ${c.ch}`} disabled={!hasYours(c)} onClick={() => onMe?.(i)} className={`${PAIR_BTN} text-you`}><IconMe /></button>
          </span>
        </div>))}
    </div>
  )
}
