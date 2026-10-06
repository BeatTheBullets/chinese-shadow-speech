import type { Segment } from '../api/types'
import { weakestResults, type FlowResult } from '../lib/flow'

interface Props {
  segments: Segment[]; results: FlowResult[]; skipped: number; elapsedS: number
  onReplayAll: () => void; onRunAgain: () => void; onEcho: (idx: number) => void; onChorus: (idx: number) => void
  onFlagWeakest: () => void; onExportWeakest: () => void; onDone: () => void; onPlayPair: (r: FlowResult) => void
}
// After a Flow run: mean score and the weakest lines to drill (Phase 2+); in Phase 1 every line with replay (§7.3).
export default function FlowSummary(p: Props) {
  const byId = new Map(p.segments.map((s) => [s.id, s]))
  const scores = new Map(p.results.map((r) => [r.segmentId, byId.get(r.segmentId)?.last_score ?? null]))
  const scored = p.results.filter((r) => scores.get(r.segmentId) != null)
  const mean = scored.length ? scored.reduce((a, r) => a + scores.get(r.segmentId)!, 0) / scored.length : null
  const weakest = weakestResults(p.results, scores, 3)
  return (
    <div className="space-y-4">
      <h2 className="text-fghi">Flow finished · {p.results.length} sentences{p.skipped ? ` · ${p.skipped} skipped` : ''} · {Math.floor(p.elapsedS / 60)} min {Math.round(p.elapsedS % 60)} s</h2>
      <div className="grid grid-cols-2 gap-3">
        <div className="bg-bg border border-line rounded p-3"><div className="text-2xl text-fghi">{mean != null ? Math.round(mean * 100) : '—'}</div><div className="text-fgdim text-sm">{mean != null ? 'mean score' : 'scores arrive in Phase 2'}</div></div>
        <div className="bg-bg border border-line rounded p-3 text-sm">
          <div className="text-[10px] uppercase tracking-widest text-fgdim mb-1">{scored.length ? 'weakest, drill these' : 'replay each line'}</div>
          {(scored.length ? weakest : p.results).map((r) => (
            <div key={r.segmentId} className="flex items-center gap-2 py-0.5"><span className="font-hanzi truncate flex-1">{byId.get(r.segmentId)?.text}</span>
              <button className="btn" onClick={() => p.onPlayPair(r)}>▶ ref+you</button><button className="btn" onClick={() => p.onEcho(r.idx)}>Echo</button><button className="btn" onClick={() => p.onChorus(r.idx)}>Chorus</button></div>))}
        </div>
      </div>
      <div className="flex gap-2 justify-center">
        <button className="btn" onClick={p.onReplayAll} disabled={!p.results.length}>▶ replay whole flow</button><button className="btn" onClick={p.onRunAgain}>↻ run again</button>
        <button className="btn" onClick={p.onFlagWeakest} disabled={!scored.length}>⚑ flag weakest 3</button><button className="btn" onClick={p.onExportWeakest} disabled={!scored.length}>A → Anki weakest 3</button>
        <button className="btn" onClick={p.onDone}>done</button>
      </div>
    </div>
  )
}
