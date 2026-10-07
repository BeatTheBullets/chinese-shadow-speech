import type { Cue, CueTone } from '../lib/cue'

const TONE: Record<CueTone, string> = { ref: 'text-ref', you: 'text-you', neutral: 'text-fgdim', ok: 'text-ok', bad: 'text-bad' }

// The current instruction (addendum §6.2), the count-in dots (§6.5) and, while the mic is open, its level (§6.3).
export default function CueLine({ cue, level, dots = 0 }: { cue: Cue; level: number | null; dots?: number }) {
  return (
    <div data-testid="cue-line" className="flex items-center justify-center gap-3 min-h-[2.5rem]">
      <span role="status" className={`text-2xl font-medium ${TONE[cue.tone]}`}><span aria-hidden="true">{cue.icon}</span> {cue.text}</span>
      {dots > 0 && <span aria-label={`starting in ${dots}`} className="text-you tracking-widest text-xl">{Array.from({ length: dots }, () => '●').join(' ')}</span>}
      {level != null && <MicMeter level={level} />}
    </div>
  )
}

export function MicMeter({ level }: { level: number }) {
  const v = Math.min(1, level * 3)
  return (
    <span role="meter" aria-label="Microphone level" aria-valuemin={0} aria-valuemax={1} aria-valuenow={v}
      className="inline-block w-24 h-2 bg-panel2 rounded overflow-hidden">
      <span className="block h-full bg-you" style={{ width: `${v * 100}%` }} />
    </span>
  )
}
