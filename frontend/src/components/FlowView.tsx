import { memo, useEffect, useRef, useState } from 'react'
import type { FlowRun, Segment } from '../api/types'
import type { Mic } from '../audio/useMic'
import type { Stage } from '../lib/cue'
import type { FlowSub } from '../lib/flow'
import type { Action } from '../lib/keys'
import { clipSpans, flowWipe, lineLead, nextLineStart } from '../lib/karaoke'
import { weekdayTime } from '../lib/time'
import { TOKENS } from '../theme/tokens'
import { dotClass } from './Drawer'
import KaraokeSentence, { GhostLine } from './KaraokeSentence'
import LiveWave from './LiveWave'
import type { SoundControls } from './SoundPopover'
import StageState from './StageState'
import Transport from './Transport'

export interface FlowViewProps {
  segments: Segment[]; current: number; pending: Set<number>; sub: FlowSub; showText: boolean
  first: number; last: number // the run's range (indexes into segments)
  stage: Stage; mic: Pick<Mic, 'snapshot'>; recordingS: number; rate: number; now: number // stage: stageOf() (listen, yourTurn, along)
  clipTime: number | null; turn: { startedAt: number; duration: number } | null
}

// Flow mode while running (main spec §7.3, addendum §6.5, style spec §3): the lesson as a transcript; the current
// line large on the stage, with the karaoke wipe, the 3 · 2 · 1 countdown wherever the count-in window runs (after:
// the stage is then getReady; along: the ring shows inside the speak-along frame, which stays, as the recording
// does), and while the learner speaks (after's turn: ghost wipe and turn bar; along: throughout) the record frame
// and the live waveform; the run's next line dimmed right below it.
export default function FlowView(p: FlowViewProps) {
  const { current } = p
  const curRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => { curRef.current?.scrollIntoView?.({ block: 'center', behavior: 'smooth' }) }, [current])
  const cur = p.segments[current]
  const next = current < p.last ? p.segments[current + 1] : undefined   // the run ends at `last`: nothing beyond it plays
  const prev = current > p.first ? p.segments[current - 1] : undefined  // played just before in this run
  const spans = cur ? clipSpans(cur.ref_alignment_json, cur.start_s) : []
  const along = p.sub === 'along'
  const k = cur
    ? flowWipe({ spans, sub: p.sub, clipTime: p.clipTime, clipDuration: cur.end_s - cur.start_s, turn: p.turn, now: p.now, rate: p.rate,
      next: along && next ? nextLineStart(cur, next, p.rate) : null, lead: along && prev ? lineLead(prev, cur, p.rate) : null })
    : { wipe: null, count: null, turnLeft: null }
  const speaking = along || p.turn != null
  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-1">
      {p.segments.map((s, i) => {
        if (i !== current) return <FlowRow key={s.id} s={s} pending={p.pending.has(s.id)} place={i < current ? 'past' : next && i === current + 1 ? 'next' : 'later'} />
        return (
          <div key={s.id} ref={curRef} className="flex gap-3 items-start px-3 rounded bg-card py-3">
            <RowMarks s={s} pending={p.pending.has(s.id)} />
            <div className="flex-1">
              <StageState stage={k.count != null && p.stage !== 'along' ? 'getReady' : p.stage} count={k.count} recordingS={p.recordingS}>
                <KaraokeSentence wipe={k.wipe} text={s.text} words={s.words_json} showHanzi={p.showText} showPinyin={p.showText} />
                {!p.showText && <GhostLine count={spans.length} wipe={k.wipe} />}
                {k.turnLeft != null && (
                  <div data-testid="turn-bar" className="h-1 bg-card rounded overflow-hidden"><div className="h-full bg-you" style={{ width: `${k.turnLeft * 100}%` }} /></div>)}
                {speaking && <LiveWave mic={p.mic} color={TOKENS.you} />}
              </StageState>
            </div>
          </div>)
      })}
    </div>
  )
}

function RowMarks({ s, pending }: { s: Segment; pending: boolean }) {
  return (<>
    <span className="w-6 text-right text-[10px] text-fgdim pt-1">{s.idx + 1}</span>
    <span className={`w-2 h-2 mt-2 rounded-full flex-none ${dotClass(s, pending)}`} />
  </>)
}

const PLACE = { past: 'text-fgdim', next: 'text-fgdim text-lg', later: 'text-fg text-sm' }
// Any line but the current one. Memoised: its props only change when the run moves on, not on every frame of the wipe.
const FlowRow = memo(function FlowRow({ s, pending, place }: { s: Segment; pending: boolean; place: keyof typeof PLACE }) {
  return (
    <div className="flex gap-3 items-start px-3 py-1 rounded">
      <RowMarks s={s} pending={pending} />
      <span data-testid={place === 'next' ? 'next-line' : undefined} className={`font-hanzi truncate ${PLACE[place]}`}>{s.text}</span>
    </div>)
})

// Flow mode before a run: which sentences, which sub-mode; and the lesson's stored runs (newest first) to replay.
export function FlowSetup({ segments, from, to, sub, onChange, onStart, runs, onReplay }: {
  segments: Segment[]; from: number; to: number; sub: FlowSub; onChange: (p: { from?: number; to?: number; sub?: FlowSub }) => void; onStart: () => void
  runs: FlowRun[]; onReplay: (run: FlowRun) => void
}) {
  const pick = (label: string, value: number, key: 'from' | 'to') => (
    <select aria-label={label} className="bg-card rounded px-1 py-0.5 text-fg" value={value} onChange={(e) => onChange({ [key]: Number(e.target.value) })}>
      {segments.map((s, i) => <option key={s.id} value={i}>{i + 1}. {s.text.length > 12 ? `${s.text.slice(0, 12)}…` : s.text}</option>)}
    </select>)
  const tab = (v: FlowSub) => <button aria-pressed={sub === v} className={`px-2 py-0.5 rounded border ${sub === v ? 'bg-card border-accent text-fg' : 'border-line'}`} onClick={() => onChange({ sub: v })}>{v}</button>
  return (
    <div className="space-y-2">
      <div className="flex items-center justify-center gap-2 text-sm text-fgdim">
        Flow from {pick('Flow from', from, 'from')} to {pick('Flow to', to, 'to')} {tab('after')}{tab('along')}
        <button className="btn" onClick={onStart}>Start</button>
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
      <button className="btn" onClick={() => onReplay(run)}>▶ replay</button>
      {runs.length > 1 && (
        <select aria-label="Run to replay" className="bg-card rounded px-1 py-0.5 text-fg" value={k} onChange={(e) => setK(Number(e.target.value))}>
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
