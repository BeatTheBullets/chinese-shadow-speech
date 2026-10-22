import { useEffect, useState, type ReactNode } from 'react'
import type { Stage } from '../lib/cue'

const R = 34, ARC = 2 * Math.PI * R // the countdown ring (viewBox 80)
const TICK_MS = 250                 // the take timer's own tick: m:ss needs no more, and nothing else re-renders for it
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`
const nowS = () => performance.now() / 1000

// The whole stage shows what to do (spec §3, mockup listen-speak.html), instead of a text line and a mic meter:
// - listen / review: a small, calm label in the speaker's colour;
// - getReady (Flow after): a big `count` in accent inside a ring that runs down, plus "Get ready";
// - yourTurn / along: a record-coloured frame round the stage, large "Your turn" ("Speak along"), a pulsing red dot
//   and the take's m:ss timer from `startedAt` (performance clock, seconds), with `autoStop`'s small "stops by itself
//   when you finish" beside it (Echo, Drill; Flow's turns end on their own clock); `wave` (the live waveform) shows.
//   No note here: nothing competes with it.
//   Along records throughout, so its frame stays while it counts in to the next line: the ring shows inside it.
// `note` is the small line saying what Enter does when nothing is going on (idle, and alongside listen and review).
// Nothing moves between stages (no page jump): the cue area under the sentence has one min-height that fits the tallest
// state, the ring is overlaid on it (absolute), and `wave` has a fixed slot, held empty while not speaking.
// No transitions on the frame: nothing may delay the moment to speak (spec §7).
export default function StageState({ stage, count = null, startedAt, autoStop = false, note, wave, children }: {
  stage: Stage; count?: 3 | 2 | 1 | null; startedAt?: number; autoStop?: boolean; note?: string; wave?: ReactNode; children?: ReactNode
}) {
  const speaking = stage === 'yourTurn' || stage === 'along'
  const ring = (place: string) => count != null && (
    <div data-testid="countdown" role="timer" aria-label={`starting in ${count}`} className={`absolute ${place} w-20 h-20 text-accent`}>
      <svg viewBox="0 0 80 80" aria-hidden="true" className="absolute inset-0 -rotate-90">
        <circle cx="40" cy="40" r={R} fill="none" strokeWidth="6" className="stroke-card" />
        <circle data-testid="countdown-arc" cx="40" cy="40" r={R} fill="none" strokeWidth="6" strokeLinecap="round" className="stroke-accent"
          strokeDasharray={ARC} strokeDashoffset={ARC * (1 - count / 3)} style={{ transition: 'stroke-dashoffset 200ms linear' }} />
      </svg>
      <span className="absolute inset-0 flex items-center justify-center text-4xl font-semibold">{count}</span>
    </div>)
  return (
    <section data-testid="stage" data-stage={stage}
      className={`rounded-2xl border-2 p-3 space-y-4 ${speaking ? 'border-record ring-4 ring-inset ring-record/20' : 'border-transparent'}`}>
      {children}
      {wave != null && <div data-testid="wave-slot" className="h-12">{speaking && wave}</div>}
      {/* min-h-28 (112 px): getReady's ring (80) over "Get ready" (28), the tallest state */}
      <div data-testid="stage-cue" className="relative min-h-28 flex flex-col items-center justify-center gap-1">
        {(stage === 'listen' || stage === 'review') && (
          <p role="status" className="flex justify-center gap-2 text-ref">
            <span aria-hidden="true">▶</span> <span>{stage === 'listen' ? 'Listening' : 'Listen — the original, then you'}</span>
          </p>)}
        {stage === 'getReady' && (<>
          {ring('top-0 left-1/2 -translate-x-1/2')}
          <p className="absolute bottom-0 inset-x-0 text-center text-accent text-lg">Get ready</p>
        </>)}
        {speaking && (<>
          {stage === 'along' && ring('right-0 top-1/2 -translate-y-1/2')}
          <p role="status" className="flex items-center gap-3">
            <span data-testid="rec-dot" aria-hidden="true" className="w-3 h-3 rounded-full bg-bad ring-4 ring-bad/25 animate-pulse" />
            <span className="text-3xl font-semibold text-bad">{stage === 'along' ? 'Speak along' : 'Your turn'}</span>
          </p>
          <p className="text-sm text-fgdim">
            <span data-testid="rec-timer" className="tabular-nums">{startedAt == null ? clock(0) : <TakeTimer startedAt={startedAt} />}</span>
            {autoStop && <> · <span className="text-fgdim">stops by itself when you finish</span></>}
          </p>
        </>)}
        {note && !speaking && stage !== 'getReady' && <p className="text-center text-sm text-fgdim">{note}</p>}
      </div>
    </section>
  )
}

// The take's m:ss since `startedAt`, on its own ~4 Hz tick: only this re-renders, not the page (it used to ride a
// per-frame clock). The interval goes with it on unmount.
function TakeTimer({ startedAt }: { startedAt: number }) {
  const [now, setNow] = useState(nowS)
  useEffect(() => {
    setNow(nowS())
    const t = window.setInterval(() => setNow(nowS()), TICK_MS)
    return () => window.clearInterval(t)
  }, [startedAt])
  return <>{clock(Math.max(0, now - startedAt))}</>
}
