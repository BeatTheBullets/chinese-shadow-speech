import { memo, useState, type ReactNode } from 'react'
import type { FlowRun, Segment } from '../api/types'
import type { Mic } from '../audio/useMic'
import type { Stage } from '../lib/cue'
import type { FlowSub } from '../lib/flow'
import type { Action } from '../lib/keys'
import { clipSpans, flowWipe, lineLead, nextLineStart } from '../lib/karaoke'
import { weekdayTime } from '../lib/time'
import { TOKENS } from '../theme/tokens'
import Button from '../ui/Button'
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
  controls?: ReactNode // the run's settings (FlowSetup): shown before a run, their space kept (hidden) while it runs
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
  // Lines from..to-1 of the window; one past either end of the lesson is an empty slot of the same height.
  const lines = (from: number, to: number) => Array.from({ length: to - from }, (_, j) => {
    const i = from + j, s = p.segments[i]
    if (!s) return <div key={`pad${i}`} data-testid="flow-pad" aria-hidden="true" className="h-8" />
    return <FlowRow key={s.id} s={s} pending={p.pending.has(s.id)} place={i < current ? 'past' : next && i === current + 1 ? 'next' : 'later'} />
  })
  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div data-testid="flow-transcript" className="mx-auto w-full max-w-2xl flex flex-col items-center gap-1">
        {p.controls != null && <div aria-hidden={p.running || undefined} className={`w-full min-h-16 ${p.running ? 'invisible' : ''}`}>{p.controls}</div>}
        {lines(current - WINDOW.before, current)}
        {cur && (
          <div data-testid="flow-current" className="w-full flex gap-3 items-start px-3 rounded bg-card py-2">
            <span className="flex items-center gap-2 pt-2"><RowMarks s={cur} pending={p.pending.has(cur.id)} /></span>
            <div className="flex-1 min-w-0">
              <StageState compact stage={k.count != null && p.stage !== 'along' ? 'getReady' : p.stage} count={k.count} startedAt={p.startedAt}
                wave={<LiveWave mic={p.mic} color={TOKENS.you} />}>
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
// Any line but the current one, centred under (or over) the stage, one fixed height. Memoised: its props only change
// when the run moves on, not on every frame of the wipe.
const FlowRow = memo(function FlowRow({ s, pending, place }: { s: Segment; pending: boolean; place: keyof typeof PLACE }) {
  return (
    <div data-testid="flow-line" className="w-full h-8 flex justify-center items-center gap-2 px-3 min-w-0">
      <RowMarks s={s} pending={pending} />
      <span data-testid={place === 'next' ? 'next-line' : undefined} className={`font-hanzi truncate ${PLACE[place]}`}>{s.text}</span>
    </div>)
})

// The Flow screen's settings, small, above the transcript (FlowView's `controls`): which sentences, which sub-mode; and
// the lesson's stored runs (newest first) to replay. No Start button here: the bar's "Start flow" (Enter, pulsing) is
// the one obvious start.
export function FlowSetup({ segments, from, to, sub, onChange, runs, onReplay }: {
  segments: Segment[]; from: number; to: number; sub: FlowSub; onChange: (p: { from?: number; to?: number; sub?: FlowSub }) => void
  runs: FlowRun[]; onReplay: (run: FlowRun) => void
}) {
  const pick = (label: string, value: number, key: 'from' | 'to') => (
    <select aria-label={label} className="inp" value={value} onChange={(e) => onChange({ [key]: Number(e.target.value) })}>
      {segments.map((s, i) => <option key={s.id} value={i}>{i + 1}. {s.text.length > 12 ? `${s.text.slice(0, 12)}…` : s.text}</option>)}
    </select>)
  const tab = (v: FlowSub) => <button aria-pressed={sub === v} className={`px-2.5 py-1 rounded-xl border ${sub === v ? 'border-accent text-accent' : 'border-line text-fgdim hover:text-fg'}`} onClick={() => onChange({ sub: v })}>{v}</button>
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-center gap-2 text-sm text-fgdim">
        Flow from {pick('Flow from', from, 'from')} to {pick('Flow to', to, 'to')} {tab('after')}{tab('along')}
      </div>
      {runs.length > 0 && <PastRuns key={`${runs[0].started_at}|${runs[0].session_id}`} runs={runs} onReplay={onReplay} />}
    </div>
  )
}

const runLabel = (r: FlowRun) => `${weekdayTime(r.started_at)} · ${r.items.length} ${r.items.length === 1 ? 'sentence' : 'sentences'}`
// The last stored run, or an older one picked from the list, to replay original → you. A newer run starts it over.
function PastRuns({ runs, onReplay }: { runs: FlowRun[]; onReplay: (run: FlowRun) => void }) {
  const [k, setK] = useState(0)
  const run = runs[Math.min(k, runs.length - 1)]
  return (
    <div data-testid="last-run" className="flex items-center justify-center gap-2 text-xs text-fgdim">
      {k === 0 ? 'Last run' : 'Earlier run'} · {runLabel(run)}
      {/* not ▶: that is Listen's (spec §2) */}
      <Button icon={<IconReplay />} label="Replay run" onClick={() => onReplay(run)} />
      {runs.length > 1 && (
        <select aria-label="Run to replay" className="inp text-xs" value={k} onChange={(e) => setK(Number(e.target.value))}>
          {runs.map((r, i) => <option key={i} value={i}>{runLabel(r)}</option>)}
        </select>)}
    </div>
  )
}

// Flow mode while running: the same bar and keys (spec §2). Enter (■ Stop) ends the run keeping the finished
// sentences, › (→) skips this sentence, Sound holds speed and volume. No going back, no Anki and nothing to replay mid-run.
export function FlowTransport({ onAction, idx, total, sound, error, hint }: {
  onAction: (a: Action) => void; idx: number; total: number; sound: SoundControls; error: string; hint: string
}) {
  return <Transport onAction={onAction} idx={idx} total={total} recording busy={false} canPrev={false} showAnki={false} sound={sound} hint={hint} error={error} />
}
