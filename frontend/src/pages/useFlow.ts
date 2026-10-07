import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { Segment } from '../api/types'
import { sleep } from '../audio/abortable'
import { sliceSamples } from '../audio/pcm'
import type { ClipPlayer } from '../audio/player'
import { toWav16k } from '../audio/recorder'
import type { Mic } from '../audio/useMic'
import { MIN_TAKE_S } from '../lib/echo'
import { sliceRangesFromActual, type FlowResult, type FlowSub } from '../lib/flow'
import { playFlow, type FlowClip } from '../lib/flowRun'
import { usePractice } from '../store/practice'
import { useSettings } from '../store/settings'

const TAIL_MS = 200 // keep recording briefly after the last clip so its slice's slack is captured
const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

export interface FlowState {
  phase: 'setup' | 'running' | 'summary'
  sub: FlowSub; from: number | null; to: number | null // the setup form; null = current sentence / last sentence
  range: { from: number; to: number } | null           // of the last run, for "run again"
  current: number
  clipTime: number | null                                   // clip-relative time of the sentence playing (karaoke)
  turn: { startedAt: number; duration: number } | null      // after: the open speaking window, on the performance.now()/1000 clock
  results: FlowResult[]; pending: Set<number>; skipped: number; elapsedS: number
}
export interface FlowDeps {
  lessonId: number
  player: ClipPlayer
  mic: Mic
  beginRun: () => AbortController         // registers the run with the page: cancelling it (mode switch, navigation, unmount) abandons it
  endRun: (run: AbortController) => void
  setError: (msg: string) => void
}
const initial: FlowState = { phase: 'setup', sub: 'after', from: null, to: null, range: null, current: 0, clipTime: null, turn: null, results: [], pending: new Set(), skipped: 0, elapsedS: 0 }

// Flow mode (§6, §7.3): one continuous recording over a range of sentences, sliced per sentence from the playback
// stamps and submitted as `flow` attempts, each to its own sentence. stop() ends the run gracefully (finished
// sentences are submitted, the one in progress is dropped); aborting the page's run abandons it with no upload.
export function useFlow(deps: FlowDeps) {
  const d = useRef(deps)
  d.current = deps
  const [state, setState] = useState<FlowState>(initial)
  const stopCtrl = useRef<AbortController | null>(null)
  const skipCtrl = useRef<AbortController | null>(null)
  const token = useRef(0)                   // bumped by clear(): late updates from an older run are ignored
  const urls = useRef<string[]>([])         // blob: URLs of the shown results, freed on clear and unmount
  const slicing = useRef<Promise<number[]> | null>(null)  // the run in progress, until its sentences are sliced
  const sliced = useRef(new Set<number>())                // every sentence sliced from a run during this visit
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    return () => { alive.current = false; urls.current.forEach((u) => URL.revokeObjectURL(u)); urls.current = [] }
  }, [])

  function clear() {
    token.current++
    urls.current.forEach((u) => URL.revokeObjectURL(u)); urls.current = []
    setState((f) => ({ ...f, phase: 'setup', clipTime: null, turn: null, results: [], pending: new Set(), skipped: 0 }))
  }

  async function start(from: number, to: number, sub: FlowSub) {
    const segments = usePractice.getState().lesson?.segments.slice(from, to + 1) ?? []
    if (!segments.length) return
    clear()
    const my = token.current
    const gapFactor = useSettings.getState().practice.flowGapFactor
    setState((f) => ({ ...f, phase: 'running', sub, range: { from, to }, current: from, clipTime: null, turn: null }))
    const startedAt = Date.now()
    let resolve!: (ids: number[]) => void
    const run = new Promise<number[]>((r) => { resolve = r })
    const done = (ids: number[]) => { if (slicing.current === run) slicing.current = null; resolve(ids) }
    slicing.current = run
    try { await sliceAndUpload(my, from, segments, sub, gapFactor, startedAt, done) }
    finally { done([]) } // no-op once the sentences were sliced
  }

  async function sliceAndUpload(my: number, from: number, segments: Segment[], sub: FlowSub, gapFactor: number, startedAt: number, done: (ids: number[]) => void) {
    const take = await record(my, segments.map((s, k) => ({ segmentId: s.id, idx: from + k, url: api.segments.audioUrl(s.id), duration: s.end_s - s.start_s })), sub, gapFactor)
    if (token.current !== my) return
    if (!take) { setState((f) => ({ ...f, phase: 'setup', clipTime: null, turn: null })); return }
    const { got, played } = take
    const sr = got.rec.sampleRate
    const ranges = sliceRangesFromActual(played.actual, sub, gapFactor)
    const takes = ranges.map((rg) => ({ rg, samples: sliceSamples(got.samples, got.rec.startTime, sr, rg.t0, rg.t1) }))
      .filter((t) => t.samples.length / sr >= MIN_TAKE_S)
      .map((t) => ({ ...t, wav: toWav16k(t.samples, sr) }))
    const results: FlowResult[] = takes.map((t) => ({ segmentId: t.rg.segmentId, idx: t.rg.idx, attemptId: null, url: URL.createObjectURL(t.wav), duration: t.samples.length / sr }))
    urls.current = results.map((x) => x.url)
    results.forEach((x) => sliced.current.add(x.segmentId))
    done(results.map((x) => x.segmentId))
    setState((f) => ({ ...f, phase: 'summary', clipTime: null, turn: null, results, pending: new Set(results.map((x) => x.segmentId)), skipped: played.skipped + ranges.length - takes.length, elapsedS: (Date.now() - startedAt) / 1000 }))
    // Each slice uploads to the sentence it was cut for. Uploads carry on even if the summary is closed meanwhile.
    const { lessonId, setError } = d.current
    const mine = (f: () => void) => { if (token.current === my) f() }
    const session_id = usePractice.getState().sessionId ?? undefined
    for (const t of takes) {
      let attemptId: number | null = null
      try {
        attemptId = (await api.segments.postAttempt(t.rg.segmentId, t.wav, { session_id, mode: 'flow' })).id
        usePractice.getState().markPractised(t.rg.segmentId)
      }
      catch (e) { mine(() => setError(`Upload failed: ${message(e)}`)) }
      mine(() => setState((f) => {
        const pending = new Set(f.pending); pending.delete(t.rg.segmentId)
        return { ...f, pending, results: f.results.map((x) => (x.segmentId === t.rg.segmentId ? { ...x, attemptId } : x)) }
      }))
    }
    // Refresh the scores even if the summary was closed meanwhile (e.g. Flow stopped by a mode switch).
    if (alive.current) {
      api.lessons.get(lessonId).then((l) => { const ps = usePractice.getState(); if (ps.lesson?.id === lessonId) ps.replaceSegments(l.segments, l.passages) }).catch(() => {})
    }
  }

  // Records continuously while the clips play. Resolves to the samples and playback stamps, or null when the run
  // was abandoned or the mic could not open; the mic is closed and the run deregistered either way.
  async function record(my: number, clips: FlowClip[], sub: FlowSub, gapFactor: number) {
    const { player, mic, setError } = d.current
    const mine = (f: () => void) => { if (token.current === my) f() }
    const run = d.current.beginRun()
    const stopper = new AbortController()
    const onAbandon = () => stopper.abort()
    run.signal.addEventListener('abort', onAbandon, { once: true })
    stopCtrl.current = stopper
    usePractice.getState().setRecording(true); setError('')
    try {
      let rec
      try { rec = await mic.open() } catch (e) { setError(`Microphone unavailable: ${message(e)}`); return null }
      if (!rec || stopper.signal.aborted) return null // abandoned, or stopped while still at the permission prompt
      const played = await playFlow({
        player, clock: mic.now, clips, sub, gapFactor, signal: stopper.signal, rate: () => usePractice.getState().rate,
        onClip: (c, skip) => { skipCtrl.current = skip; mine(() => setState((f) => ({ ...f, current: c.idx, clipTime: 0, turn: null }))) },
        onTime: (t) => mine(() => setState((f) => ({ ...f, clipTime: t }))),
        onTurn: (_c, t) => mine(() => setState((f) => ({ ...f, turn: t && { startedAt: performance.now() / 1000, duration: t.duration } }))),
      })
      if (played.error && !run.signal.aborted) setError(`Playback failed: ${message(played.error)}`)
      await sleep(TAIL_MS, run.signal)
      if (run.signal.aborted) return null // abandoned: the page has already closed the mic
      const got = mic.finish()
      return got && { got, played }
    } finally {
      run.signal.removeEventListener('abort', onAbandon)
      if (stopCtrl.current === stopper) stopCtrl.current = null
      skipCtrl.current = null
      if (!run.signal.aborted) { mic.abandon(); usePractice.getState().setRecording(false) } // after finish() this only clears the flag
      d.current.endRun(run)
    }
  }

  return {
    state,
    setForm: (p: Partial<Pick<FlowState, 'sub' | 'from' | 'to'>>) => setState((f) => ({ ...f, ...p })),
    start,
    // Ends the run gracefully; resolves to the ids of its finished sentences once they are sliced (their uploads
    // have started then, but are not waited for).
    stop: (): Promise<number[]> => {
      stopCtrl.current?.abort()
      return slicing.current ?? Promise.resolve([])
    },
    // Every sentence a run sliced during this visit, uploaded or not yet: practised in this session.
    sliced: (): number[] => [...sliced.current],
    skip: () => skipCtrl.current?.abort(),
    clear,
  }
}
