import type { Score } from '../api/types'
import { pct, warningText } from '../lib/score'

// The You track's header (main spec §7.2): overall large, then tone, segmental (Phase 3), best so far, attempts.
export default function ScoreHeader({ score, best, attempts }: { score: Score | null | undefined; best: number | null; attempts: number }) {
  const chip = 'normal-case tracking-normal rounded bg-panel2 px-1.5 py-0.5 text-fgdim'
  if (!score) return <span className="normal-case tracking-normal text-fgdim">no score yet</span>
  const warning = warningText(score)
  if (warning) return <span className="normal-case tracking-normal text-warn">{warning}</span>
  return (
    <span className="flex items-center gap-1.5">
      <span data-testid="overall" className="text-lg text-fghi normal-case tracking-normal">{pct(score.overall)}</span>
      <span className={chip}>tone {pct(score.tone_overall)}</span>
      <span className={chip}>segmental · Phase 3</span>
      {best != null && <span className={chip}>best {pct(best)}</span>}
      <span className={chip}>{attempts} attempt{attempts === 1 ? '' : 's'}</span>
    </span>
  )
}
