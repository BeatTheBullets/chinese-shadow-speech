import { cellClass, type Cell } from '../lib/cells'
import { cellTitle, pct } from '../lib/score'
import { HeardSlot } from './HeardRow'
import { IconMe, IconPlay } from '../ui/icons'

function youMark(c: Cell): string {
  if (c.status === 'unvoiced') return '∅'
  if (c.status === 'missing' || c.score == null) return '–'
  return pct(c.score)
}
// Your verdict cells, one per syllable under your track (the Echo review's only cell row, in its own section below both tracks). Every cell is the same
// fixed size and its lines cannot wrap (they truncate), and the row aligns cells at the top, so a longer label can
// never make one cell taller than its neighbours and lift it out of line. A heard slot (HeardRow) sits under each card.
// Each cell: the character, its tone and your score (click: the speaker's syllable, a pause, then yours, onCellClick),
// then two small buttons to compare one syllable by ear: ▶ the speaker says it (onSpeaker, in the speaker's colour) and
// your head, you say it (onMe, in yours). A missing or unvoiced syllable, or one not scored yet, has nothing of yours.
// highlight: cell indexes to outline (a drill's target syllables).
const CELL_SIZE = 'w-[72px] h-24'  // 72 x 96 px, HeardSlot is 72 wide too; the 94 px inside the border hold 32 + 16 + 16 px lines and the 24 px buttons with 4 px to spare for a taller fallback CJK font
const PAIR_BTN = 'w-7 h-6 rounded flex items-center justify-center bg-bg disabled:opacity-30 [&_svg]:w-3.5 [&_svg]:h-3.5'
const hasYours = (c: Cell) => c.status != null && c.status !== 'neutral' && c.status !== 'missing' && c.status !== 'unvoiced'
export default function CellRow({ cells, onCellClick, onSpeaker, onMe, highlight }: {
  cells: Cell[]; onCellClick?: (i: number) => void; onSpeaker?: (i: number) => void; onMe?: (i: number) => void; highlight?: number[]
}) {
  const heard = cells.some((x) => x.heardSound)
  return (
    <div className="flex flex-wrap items-start gap-2 justify-center">
      {cells.map((c, i) => (
        <div key={i} className="shrink-0"><div data-testid="cell"
          className={`${CELL_SIZE} shrink-0 overflow-hidden whitespace-nowrap rounded border px-0.5 flex flex-col items-center justify-center ${cellClass(c)}${highlight?.includes(i) ? ' ring-2 ring-accent' : ''}`}>
          <button type="button" data-testid="cell-compare" title={`${cellTitle(c)} · click: the speaker${hasYours(c) ? ', then you' : ''}`} onClick={() => onCellClick?.(i)}
            className="w-full flex flex-col items-center">
            <span className="block w-full truncate font-hanzi text-fg text-[28px] leading-8">{c.ch}</span>
            <span className="block w-full truncate text-[13px] leading-4 text-ref">{c.status === 'wrong' && c.target != null && c.heard != null ? `${c.target}→${c.heard}` : `${c.tone >= 0 ? c.tone : ''}`}</span>
            <span className="block w-full truncate text-xs leading-4 text-fgdim">{youMark(c)}</span>
          </button>
          <span className="flex gap-1 mt-0.5">
            <button type="button" aria-label={`Speaker says ${c.ch}`} title={`Speaker says ${c.ch}`} onClick={() => onSpeaker?.(i)} className={`${PAIR_BTN} text-ref`}><IconPlay /></button>
            <button type="button" aria-label={`You say ${c.ch}`} title={`You say ${c.ch}`} disabled={!hasYours(c)} onClick={() => onMe?.(i)} className={`${PAIR_BTN} text-you`}><IconMe /></button>
          </span>
        </div>
        {heard && <HeardSlot cell={c} />}
        </div>))}
    </div>
  )
}
