import type { Segment } from '../api/types'
import { weakestResults, type FlowResult } from '../lib/flow'
import Button from '../ui/Button'

interface Props {
  segments: Segment[]; results: FlowResult[]; skipped: number; elapsedS: number
  onReplayAll: () => void; onRunAgain: () => void; onEcho: (idx: number) => void // opens that sentence in Echo
  onFlagWeakest: () => void; onExportWeakest: () => void; onDone: () => void; onPlayPair: (r: FlowResult) => void
}
// After a Flow run: mean score and the weakest lines to drill (Phase 2+); in Phase 1 every line with replay (§7.3).
// Labels say what happens (spec §1.3); Run again is the one obvious next step, so it is the accent button.
export default function FlowSummary(p: Props) {
  const byId = new Map(p.segments.map((s) => [s.id, s]))
  const scores = new Map(p.results.map((r) => [r.segmentId, byId.get(r.segmentId)?.last_score ?? null]))
  const scored = p.results.filter((r) => scores.get(r.segmentId) != null)
  const mean = scored.length ? scored.reduce((a, r) => a + scores.get(r.segmentId)!, 0) / scored.length : null
  const weakest = weakestResults(p.results, scores, 3)
  return (
    <div className="space-y-4">
      <h2 className="text-lg text-fg font-semibold">Flow finished · {p.results.length} sentences{p.skipped ? ` · ${p.skipped} skipped` : ''} · {Math.floor(Math.round(p.elapsedS) / 60)} min {Math.round(p.elapsedS) % 60} s</h2>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="bg-panel border border-line rounded-xl p-4">
          <div className="text-3xl text-accent tabular-nums">{mean != null ? Math.round(mean * 100) : '—'}</div>
          <div className="text-fgdim text-sm">{mean != null ? 'mean score' : 'scores arrive in Phase 2'}</div>
        </div>
        <div className="bg-panel border border-line rounded-xl p-4 text-sm">
          <div className="text-[10px] uppercase tracking-widest text-fgdim mb-1">{scored.length ? 'weakest, drill these' : 'replay each line'}</div>
          {(scored.length ? weakest : p.results).map((r) => (
            <div key={r.segmentId} className="flex items-center gap-2 py-1"><span lang="zh" className="font-hanzi text-base text-fg truncate flex-1">{byId.get(r.segmentId)?.text}</span>
              <Button label="Listen + me" onClick={() => p.onPlayPair(r)} /><Button label="Open in Echo" onClick={() => p.onEcho(r.idx)} /></div>))}
        </div>
      </div>
      <div className="flex flex-wrap gap-2 justify-center">
        <Button label="Replay the whole run" onClick={p.onReplayAll} disabled={!p.results.length} />
        <Button label="Run again" variant="primary" onClick={p.onRunAgain} />
        <Button label="Flag weakest 3" onClick={p.onFlagWeakest} disabled={!scored.length} />
        <Button label="Send weakest 3 to Anki" onClick={p.onExportWeakest} disabled={!scored.length} />
        <Button label="Done" onClick={p.onDone} />
      </div>
    </div>
  )
}
