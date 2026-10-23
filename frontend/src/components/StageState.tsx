import { useEffect, useState, type ReactNode } from 'react'
import type { Stage } from '../lib/cue'

const R = 34, ARC = 2 * Math.PI * R // the countdown ring (viewBox 80)
const TICK_MS = 250                 // the take timer's own tick: m:ss needs no more, and nothing else re-renders for it
const clock = (s: number) => `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, '0')}`
const nowS = () => performance.now() / 1000

// The whole stage shows what to do (spec §3, mockup listen-speak.html), instead of a text line and a mic meter:
// - listen / review / replay: a small, calm label in the speaker's colour (replay: a stored Flow run playing back, which
//   is playback, never recording: no frame, no "Your turn"; its `wave` is the take's waveform, in the same slot);
// - getReady (Flow after): a big `count` in accent inside a ring that runs down, plus "Get ready";
// - yourTurn / along: a record-coloured frame round the stage, large "Your turn" ("Speak along"), a pulsing red dot
//   and the take's m:ss timer from `startedAt` (performance clock, seconds), with `autoStop`'s small "stops by itself
//   when you finish" beside it (Echo, Drill; Flow's turns end on their own clock); `wave` (the live waveform) shows.
//   No note here: nothing competes with it.
//   Along records throughout, so its frame stays while it counts in to the next line: the ring shows inside it.
// `note` is a page's own small guidance line (the drill's "Scoring…", "Not green yet…"), shown when nothing is going
// on and alongside listen and review. What to press next is not a line: that button pulses (Transport's pulse).
// Nothing moves between stages (no page jump; but see `slim`): the cue area under the sentence has one min-height that fits the tallest
// state, the ring is overlaid on it (absolute), and `wave` has a fixed slot, held empty while not speaking.
// `compact` (Flow, between its transcript lines): the cue area only as tall as the ring, "Get ready" beside the ring
// instead of under it, a smaller wave slot and less space between: no big empty box.
// `slim` (Echo, Drill, which have no countdown): no reserved room. While nothing is spoken (idle, listen, review) the cue
// is one slim line (min-h-8, 32 px) with the small label and the note side by side, and no wave slot; the review below
// keeps still through all of those. "Your turn" keeps its look (frame, large text, timer, live wave) but takes only the
// room it needs, so the tracks below move once when a take starts and once when it stops.
// No transitions on the frame: nothing may delay the moment to speak (spec §7).
export default function StageState({ stage, count = null, startedAt, autoStop = false, note, wave, compact = false, slim = false, children }: {
  stage: Stage; count?: 3 | 2 | 1 | null; startedAt?: number; autoStop?: boolean; note?: string; wave?: ReactNode; compact?: boolean; slim?: boolean; children?: ReactNode
}) {
  const speaking = stage === 'yourTurn' || stage === 'along'
  // slim: the line while nothing is spoken; speaking, only its content's height; a countdown (unused there) its ring's room.
  const cue = !slim ? `${compact ? 'min-h-20' : 'min-h-28'} flex-col gap-1`
    : speaking ? 'flex-col gap-1' : stage === 'getReady' ? 'min-h-28 flex-col gap-1' : 'min-h-8 flex-row flex-wrap gap-x-3 text-sm'
  const waving = speaking || stage === 'replay'
  const showWave = wave != null && (!slim || waving)
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
      className={`rounded-2xl border-2 ${slim ? 'p-2 space-y-2' : compact ? 'p-3 space-y-2' : 'p-3 space-y-4'} ${speaking ? 'border-record ring-4 ring-inset ring-record/20' : 'border-transparent'}`}>
      {children}
      {showWave && <div data-testid="wave-slot" className={compact ? 'h-10' : 'h-12'}>{waving && wave}</div>}
      {/* min-h-28 (112 px): getReady's ring (80) over "Get ready" (28), the tallest state; compact: the ring (80) alone,
          "Your turn" with its timer (~60) fits under it */}
      <div data-testid="stage-cue" className={`relative ${cue} flex items-center justify-center`}>
        {(stage === 'listen' || stage === 'review' || stage === 'replay') && (
          <p role="status" className={`flex justify-center gap-2 text-ref${slim ? ' text-sm' : ''}`}>
            <span aria-hidden="true">▶</span> <span>{stage === 'listen' ? 'Listening' : stage === 'replay' ? 'Replaying' : 'Listen — the original, then you'}</span>
          </p>)}
        {stage === 'getReady' && (compact ? (<>
          {ring('top-0 right-1/2 mr-2')}
          <p className="absolute left-1/2 ml-2 top-1/2 -translate-y-1/2 text-accent text-lg">Get ready</p>
        </>) : (<>
          {ring('top-0 left-1/2 -translate-x-1/2')}
          <p className="absolute bottom-0 inset-x-0 text-center text-accent text-lg">Get ready</p>
        </>))}
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
