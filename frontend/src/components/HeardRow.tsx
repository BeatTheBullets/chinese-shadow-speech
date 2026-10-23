import type { Cell } from '../lib/cells'

// What was heard where a sound was wrong (Phase 3a spec §1.1): one slot directly under each character card, at the
// card's width, so it stays aligned however the card row wraps; the expected pinyin is in its tooltip, and a card
// whose sound was right gets an empty slot to keep its neighbours level. CellRow renders the slots only when some
// sound slipped, and TwoTrack's "Characters" caption carries the HEARD label (HeardLabel) so it never covers a slip.
export const HeardLabel = () => <span className="text-sound">HEARD</span>
export function HeardSlot({ cell }: { cell: Cell }) {
  return (
    <div data-slot title={cell.heardSound ? `heard ${cell.heardSound} instead of ${cell.pinyin}` : undefined}
      className={`w-[72px] shrink-0 h-6 mt-1 overflow-hidden whitespace-nowrap rounded px-0.5 py-0.5 text-center${cell.heardSound ? ' border border-dashed border-sound' : ''}`}>
      {cell.heardSound && <span className="text-[13px] leading-4 text-sound font-semibold">{cell.heardSound}</span>}
    </div>
  )
}
