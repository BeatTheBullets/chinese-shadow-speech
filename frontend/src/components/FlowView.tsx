import { useEffect, useRef } from 'react'
import type { Segment } from '../api/types'
import type { FlowSub } from '../lib/flow'
import Sentence from './Sentence'
import { dotClass } from './Drawer'

// Flow mode while running: the lesson as a transcript, the current line grown in place with a live mic strip (§7.3).
export default function FlowView({ segments, current, pending, micPeak, sub, showText }: { segments: Segment[]; current: number; pending: Set<number>; micPeak: number; sub: FlowSub; showText: boolean }) {
  const curRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => { curRef.current?.scrollIntoView?.({ block: 'center', behavior: 'smooth' }) }, [current])
  return (
    <div className="flex-1 overflow-y-auto p-6 space-y-1">
      {segments.map((s, i) => {
        const isCur = i === current
        return (
          <div key={s.id} ref={isCur ? curRef : undefined} className={`flex gap-3 items-start px-3 py-1 rounded ${isCur ? 'bg-[#1c2a3a] py-3' : ''}`}>
            <span className="w-6 text-right text-[10px] text-fgdim pt-1">{s.idx + 1}</span>
            <span className={`w-2 h-2 mt-2 rounded-full flex-none ${dotClass(s, pending.has(s.id))}`} />
            {isCur ? (
              <div className="flex-1">
                <Sentence text={s.text} words={s.words_json} showHanzi={showText} showPinyin={showText} />
                <div className="flex items-center gap-2 mt-2 pl-4"><span className="w-2.5 h-2.5 rounded-full bg-bad shadow-[0_0_8px_#d9534f]" />
                  <div className="h-2 flex-1 bg-panel2 rounded overflow-hidden"><div className="h-full bg-you" style={{ width: `${Math.min(100, micPeak * 300)}%` }} /></div>
                  <span className="text-[10px] text-fgdim">{sub === 'after' ? 'your turn' : 'speak along'}</span></div>
              </div>
            ) : <span className={`font-hanzi truncate ${i < current ? 'text-fgdim' : 'text-fg text-sm'}`}>{s.text}</span>}
          </div>)
      })}
    </div>
  )
}

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

// Flow mode while running: ■ stop (Enter) · skip (→) · speed. Pause is not in v1.
export function FlowTransport({ rate, onRate, sub, onStop, onSkip, error }: { rate: number; onRate: (r: number) => void; sub: FlowSub; onStop: () => void; onSkip: () => void; error: string }) {
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
      </div>
      {error && <p className="text-xs text-bad" role="alert">{error}</p>}
    </div>
  )
}
