import type { ReactNode } from 'react'
import type { Stage } from '../lib/cue'

const R = 34, ARC = 2 * Math.PI * R // the countdown ring (viewBox 80)
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`

// The whole stage shows what to do (spec §3, mockup listen-speak.html), instead of a text line and a mic meter:
// - listen / review: a small, calm label in the speaker's colour;
// - getReady (Flow only): a big `count` in accent inside a ring that runs down, plus "Get ready";
// - yourTurn / along: a record-coloured frame round the stage, large "Your turn" ("Speak along"), a pulsing red dot
//   and the take's m:ss timer; `children` then carry the live waveform. No note here: nothing competes with it.
// `note` is the small line saying what Enter does when nothing is going on (idle, and alongside listen and review).
// No transitions on the frame: nothing may delay the moment to speak (spec §7).
export default function StageState({ stage, count = null, recordingS = 0, note, children }: {
  stage: Stage; count?: 3 | 2 | 1 | null; recordingS?: number; note?: string; children?: ReactNode
}) {
  const speaking = stage === 'yourTurn' || stage === 'along'
  return (
    <section data-testid="stage" data-stage={stage}
      className={`rounded-2xl border-2 p-3 space-y-4 ${speaking ? 'border-record ring-4 ring-inset ring-record/20' : 'border-transparent'}`}>
      {children}
      {(stage === 'listen' || stage === 'review') && (
        <p role="status" className="flex justify-center gap-2 text-ref">
          <span aria-hidden="true">▶</span> <span>{stage === 'listen' ? 'Listening' : 'Listen — the original, then you'}</span>
        </p>)}
      {stage === 'getReady' && (
        <div className="flex flex-col items-center gap-2">
          {count != null && (
            <div data-testid="countdown" role="timer" aria-label={`starting in ${count}`} className="relative w-20 h-20 text-accent">
              <svg viewBox="0 0 80 80" aria-hidden="true" className="absolute inset-0 -rotate-90">
                <circle cx="40" cy="40" r={R} fill="none" strokeWidth="6" className="stroke-card" />
                <circle data-testid="countdown-arc" cx="40" cy="40" r={R} fill="none" strokeWidth="6" strokeLinecap="round" className="stroke-accent"
                  strokeDasharray={ARC} strokeDashoffset={ARC * (1 - count / 3)} style={{ transition: 'stroke-dashoffset 200ms linear' }} />
              </svg>
              <span className="absolute inset-0 flex items-center justify-center text-4xl font-semibold">{count}</span>
            </div>)}
          <p className="text-accent text-lg">Get ready</p>
        </div>)}
      {speaking && (
        <div className="flex flex-col items-center gap-1">
          <p role="status" className="flex items-center gap-3">
            <span data-testid="rec-dot" aria-hidden="true" className="w-3 h-3 rounded-full bg-bad ring-4 ring-bad/25 animate-pulse" />
            <span className="text-3xl font-semibold text-bad">{stage === 'along' ? 'Speak along' : 'Your turn'}</span>
          </p>
          <span data-testid="rec-timer" className="text-sm text-fgdim tabular-nums">{clock(recordingS)}</span>
        </div>)}
      {note && !speaking && stage !== 'getReady' && <p className="text-center text-sm text-fgdim">{note}</p>}
    </section>
  )
}
