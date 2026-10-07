import { memo, useEffect, useRef } from 'react'
import type { Segment } from '../api/types'
import type { Cue } from '../lib/cue'
import type { FlowSub } from '../lib/flow'
import { clipSpans, flowWipe, lineLead, nextLineStart } from '../lib/karaoke'
import CueLine from './CueLine'
import { dotClass } from './Drawer'
import KaraokeSentence, { GhostLine } from './KaraokeSentence'
import VolumeSliders, { type VolumeControls } from './VolumeSliders'

export interface FlowViewProps {
  segments: Segment[]; current: number; pending: Set<number>; sub: FlowSub; showText: boolean
  first: number; last: number // the run's range (indexes into segments)
  cue: Cue; level: number | null; rate: number; now: number
  clipTime: number | null; turn: { startedAt: number; duration: number } | null
}

// Flow mode while running (main spec §7.3, addendum §6.5): the lesson as a transcript; the current line large with
// the cue line, count-in, karaoke wipe (in after: ghost wipe and turn bar during the learner's turn); the run's next
// line dimmed right below it.
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
    : { wipe: null, dots: 0, turnLeft: null }
  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-1">
      {p.segments.map((s, i) => {
        if (i !== current) return <FlowRow key={s.id} s={s} pending={p.pending.has(s.id)} place={i < current ? 'past' : next && i === current + 1 ? 'next' : 'later'} />
        return (
          <div key={s.id} ref={curRef} className="flex gap-3 items-start px-3 rounded bg-[#1c2a3a] py-3">
            <RowMarks s={s} pending={p.pending.has(s.id)} />
            <div className="flex-1 space-y-2">
              <CueLine cue={p.cue} level={p.level} dots={k.dots} />
              <KaraokeSentence wipe={k.wipe} text={s.text} words={s.words_json} showHanzi={p.showText} showPinyin={p.showText} />
              {!p.showText && <GhostLine count={spans.length} wipe={k.wipe} />}
              {k.turnLeft != null && (
                <div data-testid="turn-bar" className="h-1 bg-panel2 rounded overflow-hidden"><div className="h-full bg-you" style={{ width: `${k.turnLeft * 100}%` }} /></div>)}
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

// Flow mode before a run: which sentences, which sub-mode.
export function FlowSetup({ segments, from, to, sub, onChange, onStart }: { segments: Segment[]; from: number; to: number; sub: FlowSub; onChange: (p: { from?: number; to?: number; sub?: FlowSub }) => void; onStart: () => void }) {
  const pick = (label: string, value: number, key: 'from' | 'to') => (
    <select aria-label={label} className="bg-panel2 rounded px-1 py-0.5 text-fg" value={value} onChange={(e) => onChange({ [key]: Number(e.target.value) })}>
      {segments.map((s, i) => <option key={s.id} value={i}>{i + 1}. {s.text.length > 12 ? `${s.text.slice(0, 12)}…` : s.text}</option>)}
    </select>)
  const tab = (v: FlowSub) => <button aria-pressed={sub === v} className={`px-2 py-0.5 rounded border ${sub === v ? 'bg-[#1c2a3a] border-accent text-white' : 'border-line'}`} onClick={() => onChange({ sub: v })}>{v}</button>
  return (
    <div className="flex items-center justify-center gap-2 text-sm text-fgdim">
      Flow from {pick('Flow from', from, 'from')} to {pick('Flow to', to, 'to')} {tab('after')}{tab('along')}
      <button className="btn" onClick={onStart}>Start</button>
    </div>
  )
}

// Flow mode while running: ■ stop (Enter) · skip (→) · speed · volume. Pause is not in v1.
export function FlowTransport({ rate, onRate, sub, onStop, onSkip, error, hint, volume }: {
  rate: number; onRate: (r: number) => void; sub: FlowSub; onStop: () => void; onSkip: () => void; error: string; hint: string; volume: VolumeControls
}) {
  const b = 'px-3 py-1 rounded bg-panel2 text-sm'
  return (
    <div className="border-t border-line p-3 text-center space-y-1">
      <div className="flex justify-center gap-2 items-center">
        <button className={`${b} bg-[#5a1f26] text-[#ffd7db]`} onClick={onStop} title="Stop and save the finished sentences (Enter)">■ stop</button>
        <button className={b} onClick={onSkip} title="Skip this sentence (→)">skip ▸▸</button>
        <label className="text-xs text-fgdim flex items-center gap-1">{rate.toFixed(2)}×<input type="range" aria-label="Playback speed" min={0.6} max={1} step={0.05} value={rate}
          onChange={(e) => onRate(Number(e.target.value))} onPointerUp={(e) => e.currentTarget.blur()} /></label>
        <button className={b} onClick={() => onRate(rate === 0.75 ? 1 : 0.75)}>0.75×</button>
        <span className="text-xs text-fgdim">{sub}</span>
        <VolumeSliders volume={volume} />
      </div>
      {hint && <p className="text-xs text-warn">{hint}</p>}
      {error && <p className="text-xs text-bad" role="alert">{error}</p>}
    </div>
  )
}
