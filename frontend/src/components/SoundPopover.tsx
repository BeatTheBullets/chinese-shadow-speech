import { useCallback, useState } from 'react'
import Button from '../ui/Button'
import { IconSound } from '../ui/icons'
import Popover from '../ui/Popover'
import VolumeSliders, { type VolumeControls } from './VolumeSliders'

export interface SoundControls { rate: number; onRate: (r: number) => void; volume: VolumeControls }

// The speaker icon is sound settings (spec §2): playback speed with the old 0.75× preset, speaker volume and, where it
// applies, the guide level. A non-modal Popover, so Space/Enter/arrows keep acting on the page while it is open.
export default function SoundPopover({ sound }: { sound: SoundControls }) {
  const { rate, onRate, volume } = sound
  const [open, setOpen] = useState(false)
  const close = useCallback(() => setOpen(false), []) // stable: Popover re-attaches its listeners when onClose changes
  return (
    <Popover open={open} onClose={close}
      anchor={<Button icon={<IconSound />} label="Sound" variant="ghost" onClick={() => setOpen((o) => !o)} />}>
      <div className="w-56 space-y-3 text-xs text-fgdim">
        <div className="space-y-1">
          <div className="flex items-center justify-between"><span className="text-fg">Speed</span><span>{rate.toFixed(2)}×</span></div>
          <div className="flex items-center gap-2">
            {/* blur after a drag so Space/arrows go back to the page shortcuts instead of the slider */}
            <input type="range" className="flex-1" aria-label="Playback speed" min={0.6} max={1} step={0.05} value={rate}
              onChange={(e) => onRate(Number(e.target.value))} onPointerUp={(e) => e.currentTarget.blur()} />
            <PresetButton pressed={rate === 0.75} onClick={() => onRate(rate === 0.75 ? 1 : 0.75)} />
          </div>
        </div>
        <VolumeSliders volume={volume} />
      </div>
    </Popover>
  )
}

// The S key's toggle (0.75 ↔ 1) as a button, its key under the label like every other button.
function PresetButton({ pressed, onClick }: { pressed: boolean; onClick: () => void }) {
  return (
    <button type="button" aria-pressed={pressed} aria-label="0.75× (S)" onClick={onClick}
      className={`flex flex-col items-center rounded-xl border px-2 py-1 ${pressed ? 'border-accent text-accent' : 'border-line text-fg'}`}>
      <span>0.75×</span><span className="text-[9px] text-fgdim tracking-wider">S</span>
    </button>
  )
}
