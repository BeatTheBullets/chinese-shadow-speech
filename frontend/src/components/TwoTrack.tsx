import { useEffect, useMemo, useRef, useState } from 'react'
import type { Score, Segment } from '../api/types'
import { cellsFromWords } from '../lib/cells'
import { contourPoints, pitchRange, warpPoints } from '../lib/pitch'
import { withScore } from '../lib/score'
import CellRow from './CellRow'
import PitchLine from './PitchLine'
import Waveform from './Waveform'

interface Props {
  segment: Segment
  refPeaks: Float32Array | null; refDuration: number; refPlayhead: number | null
  youPeaks: Float32Array | null; youDuration: number; youPlayhead: number | null
  onPlayRef: () => void; onPlayYou: () => void; onPlaySyllable: (i: number) => void
  scoreHeader?: React.ReactNode
  score?: Score | null
}
export default function TwoTrack(p: Props) {
  const box = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(600)
  useEffect(() => { const ro = new ResizeObserver((e) => setWidth(e[0].contentRect.width)); if (box.current) ro.observe(box.current); return () => ro.disconnect() }, [])
  const longest = Math.max(p.refDuration, p.youDuration, 0.1)
  const pxPerSec = Math.max(1, width - 16) / longest
  const { words_json, ref_alignment_json, start_s } = p.segment
  const cells = useMemo(() => cellsFromWords(words_json, ref_alignment_json), [words_json, ref_alignment_json])
  const youCells = useMemo(() => withScore(cells, p.score), [cells, p.score])
  const sc = p.score
  const refPts = useMemo(() => (sc?.ref_contour ? contourPoints(sc.ref_contour) : []), [sc])
  const usrPts = useMemo(() => (sc?.usr_contour ? contourPoints(sc.usr_contour) : []), [sc])
  const ghost = useMemo(() => (sc?.ref_contour && sc.usr_contour ? warpPoints(sc.ref_contour, sc.usr_contour.spans) : []), [sc])
  const range = useMemo(() => pitchRange(refPts, usrPts), [refPts, usrPts])
  const ticks = useMemo(() => (ref_alignment_json ?? []).map((s) => s.end - start_s), [ref_alignment_json, start_s])
  const cap = 'flex justify-between text-[10px] uppercase tracking-widest text-fgdim mb-1'
  return (
    <div ref={box} className="space-y-2">
      <div className="bg-bg border border-line rounded p-2">
        <div className={cap}><span>Reference · {p.refDuration.toFixed(1)} s</span><button onClick={p.onPlayRef}>▶ Space</button></div>
        <div className="relative inline-block">
          <Waveform peaks={p.refPeaks} duration={p.refDuration} pxPerSec={pxPerSec} ticks={ticks} playhead={p.refPlayhead} color="#2f4a66" />
          {refPts.length > 0 && <PitchLine series={[{ points: refPts, className: 'stroke-ref' }]} pxPerSec={pxPerSec} duration={p.refDuration} height={44} range={range} />}
        </div>
        <CellRow cells={cells} variant="ref" onCellClick={p.onPlaySyllable} />
      </div>
      <div className="bg-bg border border-line rounded p-2">
        <div className={cap}><span>You{p.youDuration && p.refDuration ? ` · ${p.youDuration.toFixed(1)} s · ${(p.youDuration / p.refDuration).toFixed(2)}×` : ''}</span>
          <span className="flex items-center gap-2">{p.scoreHeader}<button onClick={p.onPlayYou} disabled={!p.youDuration}>▶ R</button></span></div>
        {p.youDuration ? (
          <div className="relative inline-block">
            <Waveform peaks={p.youPeaks} duration={p.youDuration} pxPerSec={pxPerSec} playhead={p.youPlayhead} color="#5a4a2a" />
            {usrPts.length > 0 && <PitchLine series={[{ points: ghost, className: 'stroke-ref opacity-30' }, { points: usrPts, className: 'stroke-warn' }]} pxPerSec={pxPerSec} duration={p.youDuration} height={44} range={range} />}
          </div>
        ) : <div className="h-11 text-center text-fgdim text-sm leading-[44px]">record to compare</div>}
        <CellRow cells={youCells} variant="you" />
      </div>
    </div>
  )
}
