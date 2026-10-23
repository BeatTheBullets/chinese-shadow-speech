import { useEffect, useMemo, useRef, useState } from 'react'
import type { TakeScore, Segment } from '../api/types'
import { cellsFromWords } from '../lib/cells'
import { contourPoints, pitchRange, warpPoints, type Pt } from '../lib/pitch'
import { withScore } from '../lib/score'
import { refWindow, sliceToWindow, speechWindow } from '../lib/timeline'
import CellRow from './CellRow'
import { HeardLabel } from './HeardRow'
import PitchLine from './PitchLine'
import Waveform from './Waveform'
import { TOKENS } from '../theme/tokens'
import Button from '../ui/Button'
import { IconMe, IconPlay } from '../ui/icons'

interface Props {
  segment: Segment
  refPeaks: Float32Array | null; refDuration: number; refPlayhead: number | null
  youPeaks: Float32Array | null; youDuration: number; youPlayhead: number | null
  onPlayRef: () => void; onPlayYou: () => void
  // A verdict cell's buttons: ▶ the speaker's syllable i, me your syllable i; its character both, speaker first.
  onPlaySyllable?: (i: number) => void; onPlayYouSyllable?: (i: number) => void; onCompareSyllable?: (i: number) => void
  scoreHeader?: React.ReactNode
  score?: TakeScore | null
  highlight?: number[] // syllables to outline in the cell row (a drill's targets)
}
const shift = (pts: Pt[], by: number): Pt[] => pts.map(([t, v]) => [t - by, v])
const WAVE_H = 36 // px, each waveform and its pitch line: compact, so the Echo page fits a ~900 px viewport unscrolled

// The Echo review (option B): two clean waveforms, each trimmed to its voice (lib/timeline) and drawn on one shared
// time scale from the left edge, so the longer voice fills the box and the shorter keeps its true relative length;
// then, in their own section below both tracks, one row of fixed-size verdict cards (a heard slot under each when a sound slipped). The reference's characters and pinyin are on the
// sentence card above (click one to hear it), so the reference has no cell row of its own; each verdict cell has its
// own speaker/me buttons to compare one syllable by ear.
// Each waveform is drawn at its own loudness (Waveform), so a quiet mic still shows beside the clip.
export default function TwoTrack(p: Props) {
  const box = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(600)
  useEffect(() => { const ro = new ResizeObserver((e) => setWidth(e[0].contentRect.width)); if (box.current) ro.observe(box.current); return () => ro.disconnect() }, [])
  const { words_json, ref_alignment_json, start_s } = p.segment
  const sc = p.score
  const cells = useMemo(() => cellsFromWords(words_json, ref_alignment_json), [words_json, ref_alignment_json])
  const youCells = useMemo(() => withScore(cells, sc), [cells, sc])
  // Windows, both measured by the scorer's rule so equal speech gives equal lengths: when scored, the score's reference
  // and take windows (yours already on the take's timeline); before that, the reference's alignment with the scorer's
  // tail and your take's peaks. Each then snapped to its peak buckets.
  const refWin = useMemo(() => refWindow(p.refDuration, ref_alignment_json, start_s, sc?.ref_contour?.spans, p.refPeaks),
    [p.refDuration, ref_alignment_json, start_s, sc, p.refPeaks])
  const youWin = useMemo(() => speechWindow(p.youDuration, sc?.usr_contour?.spans, p.youPeaks), [p.youDuration, sc, p.youPeaks])
  const ref = useMemo(() => refWin && sliceToWindow(p.refPeaks, p.refDuration, refWin), [p.refPeaks, p.refDuration, refWin])
  const you = useMemo(() => youWin && sliceToWindow(p.youPeaks, p.youDuration, youWin), [p.youPeaks, p.youDuration, youWin])
  const refLen = ref ? ref.to - ref.from : 0, youLen = you ? you.to - you.from : 0
  const pxPerSec = Math.max(1, width - 16) / Math.max(refLen, youLen, 0.1)
  const refFrom = ref?.from ?? 0, youFrom = you?.from ?? 0
  const refPts = useMemo(() => (sc?.ref_contour ? shift(contourPoints(sc.ref_contour), refFrom) : []), [sc, refFrom])
  const usrPts = useMemo(() => (sc?.usr_contour ? shift(contourPoints(sc.usr_contour), youFrom) : []), [sc, youFrom])
  const ghost = useMemo(() => (sc?.ref_contour && sc.usr_contour ? shift(warpPoints(sc.ref_contour, sc.usr_contour.spans), youFrom) : []), [sc, youFrom])
  const range = useMemo(() => pitchRange(refPts, usrPts), [refPts, usrPts])
  const ticks = useMemo(() => (ref_alignment_json ?? []).map((s) => s.end - start_s - refFrom), [ref_alignment_json, start_s, refFrom])
  // The speed: the scorer's (its aligned speech lengths) when scored, else the two voices' lengths. The captions give no
  // seconds: the waveforms show the lengths, and a second pair of figures measured another way would disagree with it.
  const rate = sc?.rate_ratio ?? (refWin && youWin ? youWin.speech / refWin.speech : null)
  const head = (t: number | null, from: number) => (t == null ? null : t - from)
  // Each track's caption, with its play button as on the bar (same action, same look: Listen's ▶ in accent, Me's head),
  // its key a grey hint, never the face; normal-case so the caption's small caps do not reach the button.
  // The buttons are the slim row size (sm), so a caption is one line, not a stacked button's height.
  const cap = 'flex items-center justify-between text-[10px] uppercase tracking-widest text-fgdim mb-1'
  const track = 'bg-bg border border-line rounded px-2 py-1.5'
  return (
    <div ref={box} className="space-y-2">
      <div className={track}>
        <div className={cap}><span>Reference</span>
          <span className="normal-case tracking-normal"><Button icon={<span className="text-accent"><IconPlay /></span>} label="Listen" keyHint="Space" variant="ghost" size="sm" onClick={p.onPlayRef} /></span></div>
        <div className="relative inline-block">
          <Waveform peaks={ref?.peaks ?? null} duration={refLen} pxPerSec={pxPerSec} ticks={ticks} playhead={head(p.refPlayhead, refFrom)} color={TOKENS.ref} height={WAVE_H} />
          {refPts.length > 0 && <PitchLine series={[{ points: refPts, className: 'stroke-ref' }]} pxPerSec={pxPerSec} duration={refLen} height={WAVE_H} range={range} />}
        </div>
      </div>
      <div className={track}>
        <div className={cap}><span>You{youWin && rate != null ? ` · ${rate.toFixed(2)}×` : ''}</span>
          <span className="flex items-center gap-2">{p.scoreHeader}
            <span className="normal-case tracking-normal"><Button icon={<IconMe />} label="Me" keyHint="R" variant="ghost" size="sm" onClick={p.onPlayYou} disabled={!p.youDuration} /></span></span></div>
        {p.youDuration ? (
          <div className="relative inline-block">
            <Waveform peaks={you?.peaks ?? null} duration={youLen} pxPerSec={pxPerSec} playhead={head(p.youPlayhead, youFrom)} color={TOKENS.you} height={WAVE_H} />
            {usrPts.length > 0 && <PitchLine series={[{ points: ghost, className: 'stroke-ref opacity-30' }, { points: usrPts, className: 'stroke-you' }]} pxPerSec={pxPerSec} duration={youLen} height={WAVE_H} range={range} />}
          </div>
        ) : <div className="h-9 text-center text-fgdim text-sm leading-9">record to compare</div>}
      </div>
      <div data-testid="characters">
        <div className="text-[10px] uppercase tracking-widest text-fgdim mb-1 text-center">Characters{youCells.some((c) => c.heardSound) && <> · <HeardLabel /></>}</div>
        <CellRow cells={youCells} onCellClick={p.onCompareSyllable} onSpeaker={p.onPlaySyllable} onMe={p.onPlayYouSyllable} highlight={p.highlight} />
      </div>
    </div>
  )
}
