import { useEffect, useMemo, useRef, useState } from 'react'
import type { Score, Segment } from '../api/types'
import { cellsFromWords } from '../lib/cells'
import { contourPoints, pitchRange, warpPoints } from '../lib/pitch'
import { withScore } from '../lib/score'
import CellRow from './CellRow'
import HeardRow from './HeardRow'
import PitchLine from './PitchLine'
import Waveform from './Waveform'
import { TOKENS } from '../theme/tokens'
import Button from '../ui/Button'
import { IconMe, IconPlay } from '../ui/icons'

interface Props {
  segment: Segment
  refPeaks: Float32Array | null; refDuration: number; refPlayhead: number | null
  youPeaks: Float32Array | null; youDuration: number; youPlayhead: number | null
  onPlayRef: () => void; onPlayYou: () => void; onPlaySyllable: (i: number) => void
  onPlayYouSyllable?: (i: number) => void
  scoreHeader?: React.ReactNode
  score?: Score | null
  highlight?: number[] // syllables to outline in both rows (a drill's targets)
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
  const soundMarks = useMemo(() => youCells.flatMap((c, i) => (c.heardSound ? [i] : [])), [youCells])
  const sc = p.score
  const refPts = useMemo(() => (sc?.ref_contour ? contourPoints(sc.ref_contour) : []), [sc])
  const usrPts = useMemo(() => (sc?.usr_contour ? contourPoints(sc.usr_contour) : []), [sc])
  const ghost = useMemo(() => (sc?.ref_contour && sc.usr_contour ? warpPoints(sc.ref_contour, sc.usr_contour.spans) : []), [sc])
  const range = useMemo(() => pitchRange(refPts, usrPts), [refPts, usrPts])
  const ticks = useMemo(() => (ref_alignment_json ?? []).map((s) => s.end - start_s), [ref_alignment_json, start_s])
  // Each track's caption, with its play button as on the bar (same action, same look: Listen's ▶ in accent, Me's head),
  // its key a grey hint, never the face; normal-case so the caption's small caps do not reach the button.
  const cap = 'flex items-center justify-between text-[10px] uppercase tracking-widest text-fgdim mb-1'
  return (
    <div ref={box} className="space-y-2">
      <div className="bg-bg border border-line rounded p-2">
        <div className={cap}><span>Reference · {p.refDuration.toFixed(1)} s</span>
          <span className="normal-case tracking-normal"><Button icon={<span className="text-accent"><IconPlay /></span>} label="Listen" keyHint="Space" variant="ghost" onClick={p.onPlayRef} /></span></div>
        <div className="relative inline-block">
          <Waveform peaks={p.refPeaks} duration={p.refDuration} pxPerSec={pxPerSec} ticks={ticks} playhead={p.refPlayhead} color={TOKENS.ref} />
          {refPts.length > 0 && <PitchLine series={[{ points: refPts, className: 'stroke-ref' }]} pxPerSec={pxPerSec} duration={p.refDuration} height={44} range={range} />}
        </div>
        <CellRow cells={cells} variant="ref" onCellClick={p.onPlaySyllable} highlight={p.highlight} soundMarks={soundMarks} />
      </div>
      <div className="bg-bg border border-line rounded p-2">
        <div className={cap}><span>You{p.youDuration && p.refDuration ? ` · ${p.youDuration.toFixed(1)} s · ${(p.youDuration / p.refDuration).toFixed(2)}×` : ''}</span>
          <span className="flex items-center gap-2">{p.scoreHeader}
            <span className="normal-case tracking-normal"><Button icon={<IconMe />} label="Me" keyHint="R" variant="ghost" onClick={p.onPlayYou} disabled={!p.youDuration} /></span></span></div>
        {p.youDuration ? (
          <div className="relative inline-block">
            <Waveform peaks={p.youPeaks} duration={p.youDuration} pxPerSec={pxPerSec} playhead={p.youPlayhead} color={TOKENS.you} />
            {usrPts.length > 0 && <PitchLine series={[{ points: ghost, className: 'stroke-ref opacity-30' }, { points: usrPts, className: 'stroke-you' }]} pxPerSec={pxPerSec} duration={p.youDuration} height={44} range={range} />}
          </div>
        ) : <div className="h-11 text-center text-fgdim text-sm leading-[44px]">record to compare</div>}
        <CellRow cells={youCells} variant="you" onCellClick={p.onPlayYouSyllable} highlight={p.highlight} />
        <HeardRow cells={youCells} />
      </div>
    </div>
  )
}
