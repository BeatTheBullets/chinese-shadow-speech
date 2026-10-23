import { memo, useCallback, useState, type ReactNode } from 'react'
import type { FlowRun, Segment } from '../api/types'
import type { Mic } from '../audio/useMic'
import type { Stage } from '../lib/cue'
import type { FlowSub } from '../lib/flow'
import type { Action } from '../lib/keys'
import { clipSpans, flowWipe, lineLead, nextLineStart } from '../lib/karaoke'
import { weekdayTime } from '../lib/time'
import { TOKENS } from '../theme/tokens'
import Button from '../ui/Button'
import Popover from '../ui/Popover'
import { IconReplay } from '../ui/icons'
import { dotClass } from './Drawer'
import KaraokeSentence, { GhostLine } from './KaraokeSentence'
import LiveWave from './LiveWave'
import type { SoundControls } from './SoundPopover'
import StageState from './StageState'
import Transport from './Transport'

export interface FlowViewProps {
  segments: Segment[]; current: number; pending: Set<number>; sub: FlowSub; showText: boolean
  first: number; last: number // the run's range (indexes into segments); before a run, the range Enter will start
  stage: Stage; mic: Pick<Mic, 'snapshot'>; rate: number; now: number // stage: stageOf() (idle, listen, yourTurn, along)
  startedAt: number // performance-clock second the take timer counts from: after's turn opened, or along's run began
  clipTime: number | null; turn: { startedAt: number; duration: number } | null
  running: boolean    // false: the Flow screen before a run (Enter starts it), with `controls` shown
  controls?: ReactNode // the run's settings (FlowSetup): shown before a run; while it runs nothing shows but their space is kept
  // A stored run playing back (stage 'replay', running true): `banner` says so in the settings' place, `replayWave` (the
  // take's waveform) shows in the stage's wave slot. The stage counts nothing in then: no turn follows.
  banner?: ReactNode; replayWave?: ReactNode
}

// The transcript round the stage: this many lines before the current one (above the stage) and after it (below).
export const WINDOW = { before: 2, after: 3 } as const

// Flow mode (main spec §7.3, addendum §6.5, style spec §3), from the moment it is chosen: a window of the lesson
// (WINDOW lines before and after) centred above and below a compact stage with the current line large, with the
// karaoke wipe, the 3 · 2 · 1 countdown wherever the count-in window runs (after: the stage is then getReady; along:
// the ring shows inside the speak-along frame, which stays, as the recording does), and while the learner speaks
// (after's turn: ghost wipe and turn bar; along: throughout) the record frame and the live waveform; the run's next
// line dimmed right below it. The window advances with the run; at the lesson's ends empty slots keep the stage in
// place. Before a run the stage shows the line Enter starts from, idle (or listening, when Space plays it).
export default function FlowView(p: FlowViewProps) {
  const { current } = p
  const cur = p.segments[current]
  const next = current < p.last ? p.segments[current + 1] : undefined   // the run ends at `last`: nothing beyond it plays
  const prev = current > p.first ? p.segments[current - 1] : undefined  // played just before in this run
  const spans = cur ? clipSpans(cur.ref_alignment_json, cur.start_s) : []
  const along = p.sub === 'along'
  const k = cur
    ? flowWipe({ spans, sub: p.sub, clipTime: p.clipTime, clipDuration: cur.end_s - cur.start_s, turn: p.turn, now: p.now, rate: p.rate,
      next: along && next ? nextLineStart(cur, next, p.rate) : null, lead: along && prev ? lineLead(prev, cur, p.rate) : null })
    : { wipe: null, count: null, turnLeft: null }
  const replay = p.stage === 'replay'
  const counting = k.count != null && !replay
  // Lines from..to-1 of the window; one past either end of the lesson is an empty slot of the same height.
  const lines = (from: number, to: number) => Array.from({ length: to - from }, (_, j) => {
    const i = from + j, s = p.segments[i]
    if (!s) return <div key={`pad${i}`} data-testid="flow-pad" aria-hidden="true" className="h-8" />
    return <FlowRow key={s.id} s={s} pending={p.pending.has(s.id)} place={i < current ? 'past' : next && i === current + 1 ? 'next' : 'later'} />
  })
  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div data-testid="flow-transcript" className="mx-auto w-full max-w-2xl flex flex-col items-center gap-1">
        {/* the line's height is kept while a run hides it: the content is not centred, so collapsing it would move the stage */}
        {p.controls != null && <div className="w-full min-h-9 mb-1">{!p.running ? p.controls : p.banner}</div>}
        {lines(current - WINDOW.before, current)}
        {cur && (
          <div data-testid="flow-current" className="w-full flex gap-3 items-start px-3 rounded bg-card py-2">
            <span className="flex items-center gap-2 pt-2"><RowMarks s={cur} pending={p.pending.has(cur.id)} /></span>
            <div className="flex-1 min-w-0">
              <StageState compact stage={counting && p.stage !== 'along' ? 'getReady' : p.stage} count={counting ? k.count : null} startedAt={p.startedAt}
                wave={replay ? p.replayWave : <LiveWave mic={p.mic} color={TOKENS.you} />}>
                <KaraokeSentence wipe={k.wipe} text={cur.text} words={cur.words_json} showHanzi={p.showText} showPinyin={p.showText} />
                {!p.showText && <GhostLine count={spans.length} wipe={k.wipe} />}
                {/* after's turn bar keeps its slot while listening, so the turn opening moves nothing */}
                {!along && <div className="h-1">{k.turnLeft != null && (
                  <div data-testid="turn-bar" className="h-1 bg-card rounded overflow-hidden"><div className="h-full bg-you" style={{ width: `${k.turnLeft * 100}%` }} /></div>)}</div>}
              </StageState>
            </div>
          </div>)}
        {lines(current + 1, current + 1 + WINDOW.after)}
      </div>
    </div>
  )
}

function RowMarks({ s, pending }: { s: Segment; pending: boolean }) {
  return (<>
    <span className="text-[10px] text-fgdim tabular-nums">{s.idx + 1}</span>
    <span className={`w-2 h-2 rounded-full flex-none ${dotClass(s, pending)}`} />
  </>)
}

const PLACE = { past: 'text-fgdim', next: 'text-fgdim text-lg', later: 'text-fg text-sm' }
// Any line but the current one, centred over or under the stage. Above it (already played): one fixed-height line,
// cut with an ellipsis, the full text in its title, so the stage never moves. Below it: the whole line, wrapping, since
// that is where the learner reads ahead (the next line, in along). Memoised: its props only change when the run moves
// on, not on every frame of the wipe.
const FlowRow = memo(function FlowRow({ s, pending, place }: { s: Segment; pending: boolean; place: keyof typeof PLACE }) {
  const above = place === 'past'
  return (
    <div data-testid="flow-line" className={`w-full flex justify-center gap-2 px-3 min-w-0 ${above ? 'h-8 items-center' : 'min-h-8 py-1 items-baseline'}`}>
      <RowMarks s={s} pending={pending} />
      <span data-testid={place === 'next' ? 'next-line' : undefined} title={above ? s.text : undefined}
        className={`font-hanzi ${above ? 'truncate' : 'text-center min-w-0 break-words'} ${PLACE[place]}`}>{s.text}</span>
    </div>)
})

// The Flow screen's settings, one centred line above the transcript (FlowView's `controls`): the After | Along switch,
// "Sentences a – b" opening a small pop-up (From, To, and the lesson's stored runs, newest first, when there are any),
// and Replay for the last stored run (or the one picked in the pop-up). No Start button here: the bar's "Start flow"
// (Enter, pulsing) is the one obvious start.
export function FlowSetup(p: {
  segments: Segment[]; from: number; to: number; sub: FlowSub; onChange: (p: { from?: number; to?: number; sub?: FlowSub }) => void
  runs: FlowRun[]; onReplay: (run: FlowRun) => void
}) {
  // A newer run starts the pick over (back to the latest).
  return <SetupLine key={p.runs.length ? `${p.runs[0].started_at}|${p.runs[0].session_id}` : ''} {...p} />
}

function SetupLine({ segments, from, to, sub, onChange, runs, onReplay }: Parameters<typeof FlowSetup>[0]) {
  const [open, setOpen] = useState(false)
  const close = useCallback(() => setOpen(false), []) // stable: Popover re-attaches its listeners when onClose changes
  const [k, setK] = useState(0)
  const run = runs.length ? runs[Math.min(k, runs.length - 1)] : undefined
  const pick = (label: string, value: number, key: 'from' | 'to') => (
    <label className="flex items-center justify-between gap-3">{key === 'from' ? 'From' : 'To'}
      <select aria-label={label} className="inp text-xs" value={value} onChange={(e) => { onChange({ [key]: Number(e.target.value) }); e.currentTarget.blur() }}>
        {segments.map((s, i) => <option key={s.id} value={i}>{i + 1}. {s.text.length > 12 ? `${s.text.slice(0, 12)}…` : s.text}</option>)}
      </select>
    </label>)
  const side = (v: FlowSub, label: string) => (
    <button type="button" aria-pressed={sub === v} onClick={() => onChange({ sub: v })}
      className={`px-3 py-0.5 text-xs ${sub === v ? 'bg-accent text-bg' : 'text-fgdim hover:text-fg'}`}>{label}</button>)
  return (
    <div data-testid="flow-settings" className="flex flex-wrap items-center justify-center gap-3">
      <span className="inline-flex rounded-xl border border-line overflow-hidden">{side('after', 'After')}{side('along', 'Along')}</span>
      <Popover open={open} onClose={close} side="below"
        anchor={<Button size="sm" label={`Sentences ${from + 1} – ${to + 1} ▾`} ariaExpanded={open} onClick={() => setOpen((o) => !o)} />}>
        <div className="space-y-2 text-xs text-fgdim min-w-52">
          {pick('Flow from', from, 'from')}
          {pick('Flow to', to, 'to')}
          {runs.length > 0 && (
            <label className="flex items-center justify-between gap-3">Past runs
              <select aria-label="Past runs" className="inp text-xs" value={k} onChange={(e) => setK(Number(e.target.value))}>
                {runs.map((r, i) => <option key={i} value={i}>{runLabel(r)}</option>)}
              </select>
            </label>)}
        </div>
      </Popover>
      {/* not ▶: that is Listen's (spec §2) */}
      {run && <Button size="sm" variant="ghost" icon={<IconReplay />} label={k === 0 ? 'Replay last run' : 'Replay earlier run'} onClick={() => onReplay(run)} />}
    </div>
  )
}

const runLabel = (r: FlowRun) => `${weekdayTime(r.started_at)} · ${r.items.length} ${r.items.length === 1 ? 'sentence' : 'sentences'}`

// Flow mode while running: the same bar and keys (spec §2). Enter (■ Stop) ends the run keeping the finished
// sentences, › (→) skips this sentence, Sound holds speed and volume. No going back, no Anki and nothing to replay mid-run.
export function FlowTransport({ onAction, idx, total, sound, error, hint }: {
  onAction: (a: Action) => void; idx: number; total: number; sound: SoundControls; error: string; hint: string
}) {
  return <Transport onAction={onAction} idx={idx} total={total} recording busy={false} canPrev={false} showAnki={false} sound={sound} hint={hint} error={error} />
}
