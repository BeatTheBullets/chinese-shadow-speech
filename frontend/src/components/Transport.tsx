import type { ReactNode } from 'react'
import type { Action } from '../lib/keys'
import Button from '../ui/Button'
import { IconAnki, IconChevronLeft, IconChevronRight, IconMe, IconPlay, IconRecord, IconStop } from '../ui/icons'
import SoundPopover, { type SoundControls } from './SoundPopover'

interface Props {
  onAction: (a: Action) => void; idx: number; total: number; recording: boolean; busy: boolean; hint: string; error: string
  recordLabel?: string; sound: SoundControls
  // Enter goes on to the next sentence instead of recording (the drill's Next): accent with a chevron, since red means
  // record (spec §1.3: the same action has the same look).
  advance?: boolean
  canPrev?: boolean       // false where the run only goes forward (a drill, a Flow run); default: not on the first sentence
  canNext?: boolean       // false on Practice's last sentence; default true, since a drill's or Flow run's › skips (and may end) it
  showAnki?: boolean      // the drill has no Anki
  pulse?: 'record' | 'next' // the next expected action pulses (Record / Enter, or › to move on); never while recording
}

// The control bar (spec §2), three groups left to right: where am I (‹ n / N ›), what do I do (Listen, Record, Me),
// extras (Anki, Sound). Every button says what it does; its key is the small grey hint under the label.
// recordLabel: what Enter does when not recording (Flow's start, the drill's Again/Next).
export default function Transport({ onAction, idx, total, recording, busy, hint, error, recordLabel, advance = false, sound, canPrev = idx > 0, canNext = true, showAnki = true, pulse }: Props) {
  return (
    <div data-testid="transport" className="border-t border-line bg-panel px-3.5 py-3 space-y-1">
      <div className="flex flex-wrap items-center justify-between gap-2.5">
        <div className="flex items-center gap-0.5 rounded-xl border border-line bg-card p-1">
          <Chevron icon={<IconChevronLeft />} name="Previous sentence" keyHint="←" disabled={!canPrev} onClick={() => onAction('prev')} />
          <span data-testid="position" className="px-1.5 text-xs text-accent tabular-nums" title={`Sentence ${idx + 1} of ${total}`}>{idx + 1} / {total}</span>
          <Chevron icon={<IconChevronRight />} name="Next sentence" keyHint="→" disabled={!canNext} pulse={pulse === 'next' && !recording} onClick={() => onAction('next')} />
        </div>
        <div className="flex items-center gap-2">
          {/* ▶ is Listen (the speaker), never navigation: the chevrons are */}
          <Button icon={<span className="text-accent"><IconPlay /></span>} label="Listen" keyHint="Space" onClick={() => onAction('play')} disabled={recording} />
          <Button icon={recording ? <IconStop /> : advance ? <IconChevronRight /> : <IconRecord />} label={recording ? 'Stop' : recordLabel ?? 'Record'} keyHint="Enter"
            variant={advance && !recording ? 'primary' : 'record'} size="lg" pulse={pulse === 'record' && !recording} onClick={() => onAction('record')} disabled={busy} />
          {/* nothing to hear while recording: every page ignores R then */}
          <Button icon={<IconMe />} label="Me" keyHint="R" onClick={() => onAction('replayYou')} disabled={recording} />
        </div>
        <div className="flex items-center gap-2">
          {showAnki && <Button icon={<IconAnki />} label="Anki" keyHint="A" variant="ghost" onClick={() => onAction('exportAnki')} />}
          <SoundPopover sound={sound} />
        </div>
      </div>
      {hint && <p className="text-xs text-warn text-center">{hint}</p>}
      {error && <p className="text-xs text-bad text-center" role="alert">{error}</p>}
    </div>
  )
}

// Previous/next: a thin chevron with its key under it, inside the position pill (no word: ‹ › are the word). It pulses
// as the shared Button does (.pulse-next).
function Chevron({ icon, name, keyHint, disabled, pulse, onClick }: { icon: ReactNode; name: string; keyHint: string; disabled?: boolean; pulse?: boolean; onClick: () => void }) {
  return (
    <button type="button" aria-label={`${name} (${keyHint})`} title={name} disabled={disabled} onClick={onClick}
      className={`flex min-w-[44px] flex-col items-center gap-[3px] rounded-lg px-2 py-1 text-fg disabled:opacity-40${pulse && !disabled ? ' pulse-next' : ''}`}>
      {icon}<span className="text-[9px] text-fgdim tracking-wider">{keyHint}</span>
    </button>
  )
}
