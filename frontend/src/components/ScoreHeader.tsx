import type { TakeScore } from '../api/types'
import { pct, warningText } from '../lib/score'

const HEARD_MAX = 24

// The You track's header (main spec §7.2): overall large, then tone, sounds off/ok, best so far, attempts.
export default function ScoreHeader({ score, best, attempts }: { score: TakeScore | null | undefined; best: number | null; attempts: number }) {
  const chip = 'normal-case tracking-normal rounded bg-card px-1.5 py-0.5 text-fgdim'
  if (!score) return <span className="normal-case tracking-normal text-fgdim">no score yet</span>
  const heard = Array.from(score.heard_text ?? '')
  // The header has one line: a long heard text is shortened here (the hint line keeps it whole).
  const warning = warningText(heard.length > HEARD_MAX ? { ...score, heard_text: `${heard.slice(0, HEARD_MAX).join('')}…` } : score)
  if (warning) return <span className="normal-case tracking-normal text-warn">{warning}</span>
  const soundsOff = score.sounds_off ?? -1 // absent in older scores: no chip
  return (
    <span className="flex items-center gap-1.5">
      <span data-testid="overall" className="text-lg text-fg normal-case tracking-normal">{pct(score.overall)}</span>
      <span className={chip}>tone {pct(score.tone_overall)}</span>
      {soundsOff >= 1 && <span className="normal-case tracking-normal rounded bg-card px-1.5 py-0.5 text-sound">{soundsOff} sound{soundsOff === 1 ? '' : 's'} off</span>}
      {soundsOff === 0 && (score.sounds_checked ?? 0) > 0 && <span className={chip}>sounds ok</span>}
      {best != null && <span className={chip}>best {pct(best)}</span>}
      <span className={chip}>{attempts} attempt{attempts === 1 ? '' : 's'}</span>
    </span>
  )
}
