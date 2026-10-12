import { useCallback, useEffect, useMemo, useRef, useState, type MouseEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { exportAndRecord, reexportQuestion } from '../anki/export'
import { api, ApiError } from '../api/client'
import type { Attempt, FlowRun, LessonDetail, Mode, Score, Segment, Take } from '../api/types'
import { playClip, sleep } from '../audio/abortable'
import { findSilenceEnd, sliceSamples } from '../audio/pcm'
import { ClipPlayer, peaks as peaksOf, playSequence } from '../audio/player'
import { toWav16k } from '../audio/recorder'
import { useMic } from '../audio/useMic'
import CueLine, { WithMicLevel } from '../components/CueLine'
import Drawer from '../components/Drawer'
import EditDialog from '../components/EditDialog'
import type { ExportItem } from '../components/ExportList'
import FlowSummary from '../components/FlowSummary'
import FlowView, { FlowSetup, FlowTransport } from '../components/FlowView'
import HelpOverlay from '../components/HelpOverlay'
import KaraokeSentence, { GhostLine } from '../components/KaraokeSentence'
import SessionExportDialog from '../components/SessionExportDialog'
import ScoreHeader from '../components/ScoreHeader'
import TopBar from '../components/TopBar'
import Transport from '../components/Transport'
import type { VolumeControls } from '../components/VolumeSliders'
import TwoTrack from '../components/TwoTrack'
import { cueFor, cuePhase } from '../lib/cue'
import { echoReducer, MIN_TAKE_S, type EchoEvent, type EchoState } from '../lib/echo'
import { weakestResults, type FlowResult } from '../lib/flow'
import { guidedText, nextGuidedStep, type GuidedStep } from '../lib/guided'
import { clipSpans, stageWipe } from '../lib/karaoke'
import { actionForKey, type Action } from '../lib/keys'
import { passageIndexOf, passageSpan } from '../lib/passages'
import { applyAttempt, isWarningText, warningText } from '../lib/score'
import { sessionUnsent } from '../lib/sessionExport'
import { useNow } from '../lib/useNow'
import { clamp01, guideApplies, playbackVolume } from '../lib/volume'
import { usePractice, currentSegment, currentTake, type LastAttempt, type StoredTake } from '../store/practice'
import { useSettings, defaultTextPrefs, type TextPrefs } from '../store/settings'
import { useFlow } from './useFlow'

const MOVE_ON = 'Several tries on this one. Move on and come back later.'
const HEADPHONES = 'Use headphones — the mic would pick up the reference'
const CHORUS_GAP_MS = 300  // between chorus passes (§6)
const CHORUS_TAIL_MS = 300 // the chorus take runs this long past the end of the last pass
const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
// The backend's own explanation (FastAPI `detail`) rather than the raw status line.
const readable = (e: unknown) => (e instanceof ApiError ? e.detail : message(e))

// Loads the lesson's stored takes, the newest of each sentence, unless `current()` says the page moved on meanwhile.
// Silent on failure: R then only replays the takes of this visit.
function loadTakes(lessonId: number, current: () => boolean) {
  api.lessons.takes(lessonId).then((takes: Take[]) => {
    if (!current()) return
    usePractice.getState().setStoredTakes(Object.fromEntries(takes.map((t) => [t.segment_id, stored(t.attempt_id, t.duration_s, t.score_json)])))
  }).catch(() => {})
}
const stored = (attemptId: number, duration: number, score?: Score | null): StoredTake => ({ id: attemptId, url: api.attempts.audioUrl(attemptId), duration, score })

// A multi-step run in progress. Aborting its controller (stop, mode switch, navigation, unmount) ends it.
type RunKind = 'chorus' | 'flow' | 'guided'

// Practice page: Echo, Chorus, Flow and Guided modes, the drawer's edit/split/merge and the Anki export.
// Handlers read the stores with getState() so timers and late promises never act on a stale render's values.
export default function Practice() {
  const { id } = useParams()
  const lessonId = Number(id)
  const st = usePractice()
  const settings = useSettings()
  const seg = usePractice(currentSegment)
  const segId = seg?.id
  const player = useMemo(() => new ClipPlayer(), [])
  const mic = useMic()
  const navigate = useNavigate()
  const vadTimer = useRef<number | null>(null)
  const seqCtrl = useRef<AbortController | null>(null)    // a playback sequence (reference then take, Flow replays)
  const recSeg = useRef<Segment | null>(null)             // the sentence the current recording belongs to
  const recMode = useRef<Mode>('echo')                    // the attempt mode of the current VAD recording (echo or guided)
  const runRef = useRef<{ kind: RunKind; ctrl: AbortController } | null>(null)
  const [runKind, setRunKind] = useState<RunKind | null>(null)
  const playId = useRef(0)
  const alive = useRef(true)                              // false once the page has unmounted
  const echoRef = useRef<EchoState>('idle')
  const [echo, setEcho] = useState<EchoState>('idle')
  const dispatch = (e: EchoEvent) => { echoRef.current = echoReducer(echoRef.current, e); setEcho(echoRef.current) }
  const guidedRef = useRef<GuidedStep>('listen')
  const [guided, setGuidedState] = useState<GuidedStep>('listen')
  const setGuided = (g: GuidedStep) => { guidedRef.current = g; setGuidedState(g) }
  const [refPeaks, setRefPeaks] = useState<Float32Array | null>(null)
  const [refHead, setRefHead] = useState<number | null>(null)
  const [youHead, setYouHead] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [started] = useState(() => Date.now())
  const [elapsed, setElapsed] = useState(0)
  // The edit/split dialog, on drawer row `idx`. While it is open the page shortcuts are off.
  const [dialog, setDialog] = useState<{ mode: 'edit' | 'split'; idx: number } | null>(null)
  // The session-end export dialog (addendum §5.2) and what to do once it closes.
  const [exportPrompt, setExportPrompt] = useState<{ items: ExportItem[]; after: () => void } | null>(null)
  const dialogOpen = useRef(false)
  dialogOpen.current = dialog != null || exportPrompt != null
  const [dialogBusy, setDialogBusy] = useState(false)
  const [dialogError, setDialogError] = useState('')
  const exporting = useRef(false)
  const sendingIds = useRef(new Set<number>())            // sentences an A send has in flight: not offered at session end
  const headphonesHinted = useRef(false)          // the headphones hint shows once per visit
  // The lesson's stored Flow runs, for the setup's replay; loaded on entering Flow and once a run has uploaded.
  const [flowRuns, setFlowRuns] = useState<FlowRun[]>([])
  const runsReq = useRef(0)                               // only the latest request's answer is shown
  const loadFlowRuns = useCallback(() => {
    const mine = ++runsReq.current
    api.lessons.flowRuns(lessonId).then((r) => { if (alive.current && mine === runsReq.current) setFlowRuns(r) }).catch(() => {})
  }, [lessonId])
  const flow = useFlow({ lessonId, player, mic, beginRun: () => beginRun('flow'), endRun, setError,
    onUploaded: () => { if (usePractice.getState().mode === 'flow') loadFlowRuns() } })
  const [echoTurn, setEchoTurn] = useState<number | null>(null) // performance-clock second an Echo take began (count-in, ghost wipe)
  const [help, setHelp] = useState(() => !useSettings.getState().helpSeen)
  const helpOpen = useRef(false)
  helpOpen.current = help
  // A frame clock only while something moves without media time: an Echo take's count-in and ghost wipe, Flow after's turn.
  const now = useNow(echoTurn != null || (flow.state.phase === 'running' && flow.state.turn != null))

  useEffect(() => { const t = setInterval(() => setElapsed((Date.now() - started) / 1000), 1000); return () => clearInterval(t) }, [started])
  // The help opens by itself once, on the first visit to a practice page (addendum §6.4).
  useEffect(() => { if (!useSettings.getState().helpSeen) useSettings.getState().set({ helpSeen: true }) }, [])
  // An Echo take's count-in and ghost wipe last while it records.
  useEffect(() => { if (echo !== 'recording') setEchoTurn(null) }, [echo])

  useEffect(() => {
    let cancelled = false
    setLoadError('')
    api.lessons.get(lessonId).then((l) => {
      if (cancelled) return
      const ps = usePractice.getState(), s = useSettings.getState()
      ps.setLesson(l); ps.setTextPrefs(s.textPrefs[String(lessonId)] ?? defaultTextPrefs); ps.setRate(s.practice.defaultRate)
      const seg = new URLSearchParams(window.location.search).get('seg')   // Review links here with ?seg=idx
      if (seg != null && Number.isInteger(Number(seg)) && Number(seg) >= 0 && Number(seg) < l.segments.length) ps.setIdx(Number(seg))
      loadTakes(lessonId, () => !cancelled)
    }).catch((e) => { if (!cancelled) setLoadError(`Could not load the lesson: ${message(e)}`) })
    return () => { cancelled = true }
  }, [lessonId])

  // One practice session per visit. If create() resolves after cleanup (StrictMode remount, quick navigation), end it then.
  useEffect(() => {
    let cancelled = false
    let sid: number | null = null
    const end = (sessionId: number) => { api.sessions.end(sessionId).catch(() => {}) }
    api.sessions.create(lessonId, 'echo').then((s) => {
      if (cancelled) { end(s.id); return }
      sid = s.id; usePractice.getState().setSession(s.id)
    }).catch((e) => { if (!cancelled) setError(`Could not start a practice session (attempts are still saved): ${message(e)}`) })
    return () => { cancelled = true; if (sid != null) end(sid); usePractice.getState().setSession(null) }
  }, [lessonId])

  // Leaving the page: end any run and stop audio. useMic drops the recording (including one still at the
  // permission prompt) and closes the context.
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      abortRun()
      clearVad()
      stopPlayback()
      usePractice.getState().setRecording(false)
    }
  }, [player]) // eslint-disable-line react-hooks/exhaustive-deps -- unmount-only; these touch refs and player only

  // The clip URL changes when an edit re-cuts the clip, so its waveform reloads too.
  const refUrl = segId != null ? api.segments.audioUrl(segId) : null
  useEffect(() => {
    if (refUrl == null) return
    let cancelled = false
    const url = refUrl
    void player.preload(url)
    setRefPeaks(null); setRefHead(null); setYouHead(null)
    player.peaksFor(url, 400).then((p) => { if (!cancelled) setRefPeaks(p) }).catch(() => {})
    const ps = usePractice.getState(); const nxt = ps.lesson?.segments[ps.idx + 1]
    if (nxt) void player.preload(api.segments.audioUrl(nxt.id))
    return () => { cancelled = true }
  }, [refUrl, player])

  // The You track's waveform of a stored take (this visit's takes carry their own).
  const take = currentTake(st)
  const storedUrl = take && !('peaks' in take) ? take.url : null
  const [storedPeaks, setStoredPeaks] = useState<{ url: string; peaks: Float32Array } | null>(null)
  useEffect(() => {
    if (storedUrl == null) return
    let cancelled = false
    player.peaksFor(storedUrl, 400).then((p) => { if (!cancelled) setStoredPeaks({ url: storedUrl, peaks: p }) }).catch(() => {})
    return () => { cancelled = true }
  }, [storedUrl, player])
  const youPeaks = !take ? null : 'peaks' in take ? take.peaks : storedPeaks?.url === take.url ? storedPeaks.peaks : null

  useEffect(() => { if (st.mode === 'flow') loadFlowRuns() }, [st.mode, loadFlowRuns])

  // Guided starts over on every new sentence and mode.
  useEffect(() => { setGuided('listen') }, [segId, st.mode])

  // Reference volume, or its guide level while the learner speaks along (addendum §7); follows the sliders live.
  const speakingAlong = runKind === 'chorus' || (runKind === 'flow' && flow.state.sub === 'along')
  const playVolume = playbackVolume({ speakingAlong, referenceVolume: settings.referenceVolume, guideLevel: settings.guideLevel })
  useEffect(() => { player.setVolume(playVolume) }, [player, playVolume])

  function beginRun(kind: RunKind): AbortController {
    const ctrl = new AbortController()
    runRef.current = { kind, ctrl }; setRunKind(kind)
    applyVolume(kind === 'chorus' || (kind === 'flow' && flow.state.sub === 'along'))
    return ctrl
  }
  function endRun(ctrl: AbortController) { if (runRef.current?.ctrl === ctrl) { runRef.current = null; setRunKind(null); applyVolume(false) } }
  function abortRun() { const r = runRef.current; if (!r) return; runRef.current = null; setRunKind(null); applyVolume(false); r.ctrl.abort() }
  // At once, before the run's first clip (the effect above follows a render later).
  function applyVolume(along: boolean) {
    const s = useSettings.getState()
    player.setVolume(playbackVolume({ speakingAlong: along, referenceVolume: s.referenceVolume, guideLevel: s.guideLevel }))
  }
  function hintHeadphones() {
    if (headphonesHinted.current) return
    headphonesHinted.current = true
    usePractice.getState().setHint(HEADPHONES)
  }
  function clearVad() { if (vadTimer.current != null) { clearTimeout(vadTimer.current); vadTimer.current = null } }
  function stopPlayback() {
    seqCtrl.current?.abort(); seqCtrl.current = null
    player.stop()
  }
  const busy = () => echoRef.current === 'recording' || echoRef.current === 'uploading' || runRef.current != null

  // Abandons whatever is in flight (run, recording, pending mic prompt, playback) and returns to idle.
  function cancelActivity() {
    abortRun()
    mic.abandon()
    clearVad()
    stopPlayback()
    usePractice.getState().setRecording(false)
    dispatch('CANCEL')
  }

  async function playRef() {
    const s = currentSegment(usePractice.getState())
    if (!s || busy()) return
    stopPlayback(); setError('')
    const mine = ++playId.current
    dispatch('PLAY')
    try { await player.play(api.segments.audioUrl(s.id), usePractice.getState().rate, setRefHead) }
    catch (e) { if (mine === playId.current) setError(`Could not play the reference: ${message(e)}`) }
    finally { if (mine === playId.current && echoRef.current === 'playing') dispatch('PLAY_DONE') }
  }

  async function startRecording(mode: Mode = 'echo') {
    const s = currentSegment(usePractice.getState())
    if (!s || busy()) return
    stopPlayback()
    recSeg.current = s; recMode.current = mode
    dispatch('RECORD'); usePractice.getState().setRecording(true); setError('')
    try {
      const rec = await mic.open()
      if (!rec) return
      if (mode === 'echo') setEchoTurn(performance.now() / 1000)
      // Stop after 1.2 s of silence following speech
      const tick = () => {
        vadTimer.current = null
        if (findSilenceEnd(rec.snapshot(), rec.sampleRate) != null) void stopRecording()
        else vadTimer.current = window.setTimeout(tick, 200)
      }
      vadTimer.current = window.setTimeout(tick, 400)
    } catch (e) {
      usePractice.getState().setRecording(false)
      setError(`Microphone unavailable: ${message(e)}`)
      dispatch('RECORD_FAILED')
    }
  }

  async function stopRecording() {
    if (echoRef.current !== 'recording') return
    if (!mic.capturing()) { cancelActivity(); return } // still at the permission prompt: abandon it
    clearVad()
    dispatch('STOP')
    const s = recSeg.current
    recSeg.current = null
    await finishRecording(recMode.current, s)
  }

  // Stops capture, keeps the take (or its `range` on the recording clock) as the last attempt, uploads it and plays
  // reference then take back to back. `s` is the sentence the recording started on: the take always uploads there.
  async function finishRecording(mode: Mode, s: Segment | null, range?: [number, number]) {
    const ps = usePractice.getState()
    const got = mic.finish()
    ps.setRecording(false)
    if (!s || !got) { dispatch('CANCEL'); return }
    const { rec } = got
    const samples = range ? sliceSamples(got.samples, rec.startTime, rec.sampleRate, range[0], range[1]) : got.samples
    const duration = samples.length / rec.sampleRate
    if (duration < MIN_TAKE_S) { dispatch('CANCEL'); setError('Too short to keep, nothing was saved. Try again.'); return }
    const wav = toWav16k(samples, rec.sampleRate)
    // Once uploaded, the take is the sentence's newest stored one, with its score (what R replays after moving away and back).
    const uploaded = (a: Attempt) => {
      const cur = usePractice.getState()
      cur.markPractised(s.id); cur.recordTake(s.id, stored(a.id, duration, a.score_json))
      const now = cur.lesson?.segments.find((x) => x.id === s.id)
      if (now) cur.updateSegment(applyAttempt(now, a.score_json?.overall))
      // The take's warning, or clearing an earlier take's, belongs under its own sentence only (not the one moved to).
      if (currentSegment(cur)?.id !== s.id) return
      const why = warningText(a.score_json)
      if (why) cur.setHint(why)
      else if (isWarningText(cur.hint)) cur.setHint('')
    }
    // The store moved to another sentence meanwhile (e.g. the lesson reloaded): save the take, skip the playback.
    if (currentSegment(ps)?.id !== s.id) {
      dispatch('CANCEL')
      api.segments.postAttempt(s.id, wav, { session_id: ps.sessionId ?? undefined, mode })
        .then(uploaded).catch((e) => setError(`Upload failed: ${readable(e)}`))
      return
    }
    const url = URL.createObjectURL(wav)
    const take: LastAttempt = { id: 0, url, duration, peaks: peaksOf(samples, 400) }
    ps.setLastAttempt(take); ps.bumpAttempts()
    if (usePractice.getState().attemptsThisSegment >= useSettings.getState().practice.moveOnAfter) ps.setHint(MOVE_ON)
    const upload = api.segments.postAttempt(s.id, wav, { session_id: ps.sessionId ?? undefined, mode })
      .then((a) => { uploaded(a); const cur = usePractice.getState(); if (cur.lastAttempt?.url === url) cur.setLastAttempt({ ...take, id: a.id, score: a.score_json }) })
      .catch((e) => setError(`Upload failed: ${readable(e)}`))
    dispatch('UPLOADED')
    const ctrl = new AbortController()
    seqCtrl.current = ctrl
    let heard = false
    try {
      await playSequence(player, [{ url: api.segments.audioUrl(s.id), rate: ps.rate, onTime: setRefHead }, { url, rate: 1, onTime: setYouHead }], 250, ctrl.signal)
      heard = !ctrl.signal.aborted
    } catch (e) {
      if (!ctrl.signal.aborted) setError(`Playback failed: ${message(e)}`)
    } finally {
      if (seqCtrl.current === ctrl) seqCtrl.current = null
      if (echoRef.current === 'playback') dispatch('PLAYBACK_DONE')
    }
    if (heard && mode === 'guided') guidedAdvance(s)
    await upload
  }

  // Chorus (§6): the clip N times with 300 ms gaps while you speak along; the last pass (to its end + 0.3 s) is the
  // take. The mic opens before the first pass so a permission prompt or start-up delay never cuts into the take.
  async function chorus() {
    const s = currentSegment(usePractice.getState())
    if (!s || busy()) return
    stopPlayback(); setError(''); hintHeadphones()
    const run = beginRun('chorus'), { signal } = run
    const passes = Math.max(1, Math.round(useSettings.getState().practice.chorusPasses))
    const url = api.segments.audioUrl(s.id)
    const rate = () => usePractice.getState().rate
    dispatch('PLAY')
    try {
      try {
        if (!(await mic.open())) return
      } catch (e) {
        if (!signal.aborted) { setError(`Microphone unavailable: ${message(e)}`); cancelActivity() }
        return
      }
      for (let i = 1; i < passes && !signal.aborted; i++) { await playClip(player, url, rate(), signal, setRefHead); await sleep(CHORUS_GAP_MS, signal) }
      if (signal.aborted) return
      dispatch('RECORD'); usePractice.getState().setRecording(true)
      const t0 = mic.now()
      await playClip(player, url, rate(), signal, setRefHead)
      await sleep(CHORUS_TAIL_MS, signal)
      if (signal.aborted) return
      const t1 = mic.now()
      endRun(run)
      dispatch('STOP')
      await finishRecording('chorus', s, [t0, t1])
    } catch (e) {
      if (!signal.aborted) { setError(`Could not play the reference: ${message(e)}`); cancelActivity() }
    } finally {
      endRun(run)
    }
  }

  // Guided (§6), one Enter per step: listen once → one chorus pass with the text visible (not recorded) →
  // an Echo take with the text hidden, scored; once its playback ends, on to the next sentence.
  async function guidedNext() {
    const step = guidedRef.current
    if (step === 'record') { void startRecording('guided'); return }
    const s = currentSegment(usePractice.getState())
    if (!s || busy()) return
    stopPlayback(); setError('')
    const run = beginRun('guided')
    dispatch('PLAY')
    try {
      await playClip(player, api.segments.audioUrl(s.id), usePractice.getState().rate, run.signal, setRefHead)
      if (!run.signal.aborted) setGuided(nextGuidedStep(step) ?? 'listen')
    } catch (e) {
      if (!run.signal.aborted) setError(`Could not play the reference: ${message(e)}`)
    } finally {
      if (!run.signal.aborted && echoRef.current === 'playing') dispatch('PLAY_DONE')
      endRun(run)
    }
  }
  function guidedAdvance(s: Segment) {
    const ps = usePractice.getState()
    if (ps.mode !== 'guided' || currentSegment(ps)?.id !== s.id) return
    setGuided('listen')
    goTo(ps.idx + 1)
  }

  function playSolo(play: () => Promise<void>) {
    if (busy()) return
    stopPlayback()
    play().catch((e) => setError(`Could not play: ${message(e)}`))
  }
  function playItems(items: { url: string; rate: number }[]) {
    if (busy()) return
    stopPlayback()
    const ctrl = new AbortController()
    seqCtrl.current = ctrl
    playSequence(player, items, 250, ctrl.signal)
      .catch((e) => { if (!ctrl.signal.aborted) setError(`Playback failed: ${message(e)}`) })
      .finally(() => { if (seqCtrl.current === ctrl) seqCtrl.current = null })
  }
  // This visit's take of the sentence, or its stored one when that is newer; with neither, nothing.
  function replayYou() {
    const take = currentTake(usePractice.getState())
    if (take) playSolo(() => player.play(take.url, 1, setYouHead))
  }
  // Plays one syllable of the reference once (addendum §1.2); clicking again plays it again.
  // Alignment times are source-absolute, the clip starts at seg.start_s.
  function playSyllable(cell: number) {
    const ps = usePractice.getState(), s = currentSegment(ps), span = s?.ref_alignment_json?.[cell]
    if (!s || !span) return
    const url = api.segments.audioUrl(s.id, 'wav'), from = Math.max(0, span.start - s.start_s), to = Math.max(0, span.end - s.start_s)
    playSolo(() => player.playRange(url, ps.rate, from, to, setRefHead))
  }

  function goTo(i: number) {
    const ps = usePractice.getState(), n = ps.lesson?.segments.length ?? 0
    const j = Math.max(0, Math.min(n - 1, i))
    if (n === 0 || j === ps.idx) return
    cancelActivity(); setError('')
    ps.setIdx(j)
  }
  // Clicking the active mode does nothing. Leaving Flow mid-run stops it gracefully first (the finished sentences
  // are still sliced and uploaded) and then switches.
  async function switchMode(m: Mode) {
    if (m === usePractice.getState().mode) return
    if (runRef.current?.kind === 'flow') await flow.stop()
    if (!alive.current) return
    cancelActivity(); flow.clear(); flow.setForm({ from: null, to: null })
    usePractice.getState().setMode(m)
  }

  // Flow: the setup form's range, defaulting to the current sentence's passage (addendum §4), or to the current
  // sentence through the last when the lesson has no passages.
  function flowRange() {
    const ps = usePractice.getState(), segs = ps.lesson?.segments ?? [], last = Math.max(0, segs.length - 1)
    const clamp = (i: number) => Math.max(0, Math.min(last, i))
    const passages = ps.lesson?.passages ?? []
    const k = passageIndexOf(passages, segs, ps.idx)
    const span = k >= 0 ? passageSpan(passages[k], segs) : null
    const from = clamp(flow.state.from ?? span?.from ?? ps.idx), to = clamp(flow.state.to ?? span?.to ?? last)
    return { from: Math.min(from, to), to: Math.max(from, to) }
  }
  // The top bar's passage selector: to the passage's first sentence (Flow's range follows it). Not during a Flow run.
  function pickPassage(k: number) {
    const l = usePractice.getState().lesson, p = l?.passages?.[k]
    const span = l && p ? passageSpan(p, l.segments) : null
    if (!span || runRef.current?.kind === 'flow') return
    flow.setForm({ from: null, to: null })
    goTo(span.from)
  }
  function startFlow(from: number, to: number) {
    cancelActivity()
    usePractice.getState().setHint('') // a stale move-on or Anki hint would show through the run
    if (flow.state.sub === 'along') hintHeadphones()
    void flow.start(from, to, flow.state.sub)
  }
  // From the Flow summary to a drill of one sentence.
  async function drill(mode: Mode, i: number) {
    await switchMode(mode)
    const ps = usePractice.getState()
    if (i !== ps.idx) ps.setIdx(i)
    if (mode === 'chorus') void chorus()
  }
  function flagWeakest() {
    const scores = new Map((usePractice.getState().lesson?.segments ?? []).map((s) => [s.id, s.last_score]))
    for (const r of weakestResults(flow.state.results, scores, 3)) {
      api.segments.patch(r.segmentId, { difficulty_flag: true }).then(usePractice.getState().updateSegment).catch((e) => setError(`Could not flag: ${readable(e)}`))
    }
  }
  // Original then take, for one sentence of a Flow run.
  const pairOf = (segmentId: number, takeUrl: string) => [{ url: api.segments.audioUrl(segmentId), rate: usePractice.getState().rate }, { url: takeUrl, rate: 1 }]
  const resultPair = (r: FlowResult) => pairOf(r.segmentId, r.url)
  // A stored run, original → you per sentence (its items come in sentence order); stops like any playback.
  const replayRun = (run: FlowRun) => playItems(run.items.flatMap((it) => pairOf(it.segment_id, api.attempts.audioUrl(it.attempt_id))))

  // Edit, split and merge rebuild sentences on the server. Everything in flight stops first; afterwards the lesson
  // reloads and stays on the current sentence if it still exists, else on `fallbackId`, else the same position.
  // `change` resolves to the ids whose clip it re-cut; its failure rejects. A failed reload after a successful change
  // only shows an error, so the caller never offers to repeat a change that was already made.
  async function changeSegments(change: () => Promise<number[]>, fallbackId?: number) {
    cancelActivity()
    const changed = await change()
    changed.forEach((id) => api.segments.clipChanged(id))
    let l: LessonDetail
    try { l = await api.lessons.get(lessonId) }
    catch (e) { if (alive.current) setError(`The change was saved, but the lesson could not reload: ${readable(e)}`); return }
    const ps = usePractice.getState()
    if (!alive.current || ps.lesson?.id !== lessonId) return
    const curId = currentSegment(ps)?.id
    const find = (id: number | undefined) => (id == null ? -1 : l.segments.findIndex((x) => x.id === id))
    const kept = find(curId)
    let j = kept >= 0 ? kept : find(fallbackId)
    if (j < 0) j = Math.max(0, Math.min(l.segments.length - 1, ps.idx))
    ps.replaceSegments(l.segments, l.passages)
    loadTakes(lessonId, () => alive.current && usePractice.getState().lesson?.id === lessonId)
    if (ps.mode === 'flow') loadFlowRuns() // a stored run may name a sentence that was merged away
    // A new sentence or a re-cut clip drops the last take (setIdx); otherwise only the position follows the sentence.
    if (kept < 0 || changed.includes(curId!)) ps.setIdx(j)
    else if (j !== ps.idx) usePractice.setState({ idx: j })
  }
  function openDialog(mode: 'edit' | 'split', i: number) {
    cancelActivity()
    setDialogError(''); setDialogBusy(false); setDialog({ mode, idx: i })
  }
  // Applies a dialog action to the row it was opened on (not the current sentence); the dialog stays open on failure.
  function applyDialog(what: string, change: (target: Segment) => Promise<number[]>) {
    const target = dialog && usePractice.getState().lesson?.segments[dialog.idx]
    if (!target || dialogBusy) return
    setDialogBusy(true); setDialogError('')
    changeSegments(() => change(target))
      .then(() => setDialog(null))
      .catch((e) => setDialogError(`${what}: ${readable(e)}`))
      .finally(() => setDialogBusy(false))
  }
  function saveEdit(text: string) {
    const target = dialog && usePractice.getState().lesson?.segments[dialog.idx]
    if (target && text.trim() === target.text) { setDialog(null); return } // unchanged: nothing to re-align
    applyDialog('Could not save the edit', (t) => api.segments.patch(t.id, { text }).then(() => [t.id]))
  }
  function splitAt(at: number) {
    applyDialog('Could not split', (t) => api.segments.resplit(t.id, at).then((halves) => halves.map((x) => x.id)))
  }
  function mergeNext(i: number) {
    const target = usePractice.getState().lesson?.segments[i]
    if (!target) return
    setError('')
    changeSegments(() => api.segments.mergeNext(target.id).then(() => [target.id]), target.id)
      .catch((e) => setError(e instanceof ApiError && e.detail === 'no next segment' ? 'There is no next sentence to merge with.' : `Could not merge: ${readable(e)}`))
  }

  // Sends sentences to Anki one after another (a duplicate asks before it is added) and records each new note on
  // its sentence. The only write to Anki.
  async function sendToAnki(segs: Segment[]) {
    const { exportNote, ankiUrl } = useSettings.getState()
    if (!exportNote) { setError('Configure the export note type in Settings'); return }
    if (exporting.current || !segs.length) return
    exporting.current = true; setError('')
    segs.forEach((s) => sendingIds.current.add(s.id))
    let sent = 0
    const failed: string[] = []
    try {
      for (const s of segs) {
        try {
          const updated = await exportAndRecord(s, ankiUrl, exportNote, usePractice.getState().lesson ?? undefined); sent++
          if (alive.current) usePractice.getState().updateSegment(updated)
        }
        catch (e) { failed.push(message(e)) }
        finally { sendingIds.current.delete(s.id) }
      }
    } finally { exporting.current = false }
    if (!alive.current) return
    if (failed.length) setError(`Anki export failed: ${failed.join(' ')}`)
    if (sent) usePractice.getState().setHint(sent === 1 ? 'Sent to Anki' : `Sent ${sent} sentences to Anki`)
  }
  function exportWeakest() {
    const segs = usePractice.getState().lesson?.segments ?? []
    const byId = new Map(segs.map((s) => [s.id, s]))
    const weakest = weakestResults(flow.state.results, new Map(segs.map((s) => [s.id, s.last_score])), 3)
    void sendToAnki(weakest.map((r) => byId.get(r.segmentId)).filter((s): s is Segment => s != null))
  }
  // This session's practised sentences with no Anki note (and none on its way there). A Flow run's sentences count
  // as soon as they are sliced, before their uploads finish.
  function unsentItems(): ExportItem[] {
    const ps = usePractice.getState(), l = ps.lesson
    if (!l) return []
    return sessionUnsent(l.segments, [...ps.practised, ...flow.sliced()]).filter((s) => !sendingIds.current.has(s.id)).map((segment) => ({ segment, lesson: l }))
  }
  // Offers them before `after` (leaving the page, closing the Flow summary); with none, runs `after` at once.
  function offerExport(after: () => void) {
    const items = unsentItems()
    if (!items.length) { after(); return }
    cancelActivity()
    setExportPrompt({ items, after })
  }
  // The ⌂ Library link. A click that opens a new tab or window is the browser's. A Flow run is stopped gracefully first (its
  // finished sentences are sliced and offered at once, their uploads carry on); with nothing to offer it just navigates.
  function leave(e: MouseEvent<HTMLAnchorElement>) {
    if (e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return
    const inFlow = runRef.current?.kind === 'flow'
    if (!inFlow && !unsentItems().length) return
    e.preventDefault()
    void (async () => {
      if (inFlow) await flow.stop()
      if (alive.current) offerExport(() => navigate('/library'))
    })()
  }
  function closeExport() {
    const p = exportPrompt
    setExportPrompt(null)
    p?.after()
  }

  function act(a: Action) {
    const ps = usePractice.getState()
    if (ps.lesson?.id !== lessonId) return // the store still holds another lesson (this one is loading)
    if (a === 'help') { setHelp(true); return }
    const run = runRef.current
    if (run?.kind === 'flow') { // while Flow runs: Enter stops (finished sentences are kept), → skips, speed works
      if (a === 'record') void flow.stop()
      else if (a === 'next') flow.skip()
      else if (a === 'speed075') ps.setRate(ps.rate === 0.75 ? 1 : 0.75)
      return
    }
    const savePrefs = (p: TextPrefs) => { ps.setTextPrefs(p); useSettings.getState().setTextPrefs(lessonId, p) }
    const prefs = ps.textPrefs
    switch (a) {
      case 'play': void playRef(); return
      case 'record':
        if (run) { cancelActivity(); return } // Enter stops a Chorus or a Guided playback
        if (ps.mode === 'flow') { const r = flowRange(); startFlow(r.from, r.to); return }
        if (ps.mode === 'chorus') { void chorus(); return }
        if (ps.mode === 'guided' && echoRef.current !== 'recording') { void guidedNext(); return }
        void (echoRef.current === 'recording' ? stopRecording() : startRecording()); return
      case 'chorus':
        if (run) { if (run.kind === 'chorus') cancelActivity(); return }
        void chorus(); return
      case 'prev': goTo(ps.idx - 1); return
      case 'next': goTo(ps.idx + 1); return
      case 'toggleHanzi': savePrefs({ ...prefs, hanzi: !prefs.hanzi }); return
      case 'togglePinyin': savePrefs({ ...prefs, pinyin: !prefs.pinyin }); return
      case 'toggleTranslation': savePrefs({ ...prefs, translation: !prefs.translation }); return
      case 'toggleDrawer': ps.toggleDrawer(); return
      case 'speed075': ps.setRate(ps.rate === 0.75 ? 1 : 0.75); return
      case 'replayYou': replayYou(); return
      case 'flag': {
        const s = currentSegment(ps)
        if (s) api.segments.patch(s.id, { difficulty_flag: !s.difficulty_flag }).then(usePractice.getState().updateSegment).catch((e) => setError(`Could not flag: ${readable(e)}`))
        return
      }
      case 'exportAnki': {
        const s = currentSegment(ps), ask = s && reexportQuestion(s)
        if (s && (!ask || window.confirm(ask))) void sendToAnki([s])
        return
      }
      default: return
    }
  }
  const actRef = useRef(act)
  actRef.current = act
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (dialogOpen.current || helpOpen.current) return // a dialog or the help keeps its own keys (even with focus outside it, e.g. on the body)
      if (e.defaultPrevented) return                       // already taken, e.g. the key that closed the help
      const a = actionForKey(e)
      if (!a) return
      e.preventDefault()
      // The shortcut acts on the page, so a focused button or link must not also be activated by Space/Enter.
      if (e.target instanceof HTMLElement && e.target !== document.body) e.target.blur()
      actRef.current(a)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const back = <Link to="/library" className="underline">Back to the library</Link>
  if (loadError) return <div className="p-8 text-bad">{loadError} {back}</div>
  if (!st.lesson || st.lesson.id !== lessonId) return <div className="p-8 text-fgdim">Loading…</div>
  if (!seg) return <div className="p-8 text-fgdim">This lesson has no sentences yet. {back}</div>
  const segments = st.lesson.segments
  const passages = st.lesson.passages ?? []
  const hide = st.recordingNow && settings.practice.hideTextWhileRecording
  const show = !hide && (st.mode !== 'guided' || guidedText(guided).showText)
  const fs = flow.state
  const flowRunning = fs.phase === 'running'
  const recordLabel = runKind === 'chorus' || runKind === 'guided' ? '■ stop'
    : st.mode === 'chorus' ? `● Chorus ×${settings.practice.chorusPasses}`
    : st.mode === 'guided' ? `● ${guidedText(guided).label}`
    : st.mode === 'flow' ? '● Start flow' : undefined
  const range = flowRange()
  const volume: VolumeControls = {
    // A Chorus started with C from Echo or Guided plays at the guide level too.
    reference: settings.referenceVolume, guide: guideApplies(st.mode, fs.sub) || runKind === 'chorus' ? settings.guideLevel : null,
    onReference: (v) => settings.set({ referenceVolume: clamp01(v) }), onGuide: (v) => settings.set({ guideLevel: clamp01(v) }),
  }
  const spans = clipSpans(seg.ref_alignment_json, seg.start_s)
  const refPlaying = echo === 'playing' || echo === 'playback' || runKind === 'chorus' || runKind === 'guided'
  const { wipe, dots } = stageWipe({ spans, refPlaying, refHead, turnStart: st.mode === 'echo' ? echoTurn : null, now, rate: st.rate })
  const cue = cueFor(st.mode, {
    phase: cuePhase({ mode: st.mode, echo, runKind, guided, hasTake: st.lastAttempt != null, flowPhase: fs.phase, flowSub: fs.sub, flowTurn: fs.turn != null }),
    guided, error: !!error,
  })
  return (
    <div className="h-full flex flex-col">
      <TopBar title={st.lesson.title} speaker={st.lesson.speaker} idx={flowRunning ? fs.current : st.idx} total={segments.length} mode={st.mode}
        onMode={(m) => void switchMode(m)} elapsedS={elapsed} chorusPasses={settings.practice.chorusPasses} onHelp={() => setHelp(true)}
        onBack={leave}
        passage={passages.length ? { index: passageIndexOf(passages, segments, flowRunning ? fs.current : st.idx), titles: passages.map((p) => p.title), onPick: pickPassage } : null} />
      <div className="flex-1 flex min-h-0">
        <main className="flex-1 flex flex-col min-w-0">
          {flowRunning ? (<>
            <WithMicLevel mic={mic}>{(level) => (
              <FlowView segments={segments} current={fs.current} first={fs.range?.from ?? 0} last={fs.range?.to ?? segments.length - 1}
                pending={fs.pending} sub={fs.sub} rate={st.rate} now={now}
                cue={cue} level={level} clipTime={fs.clipTime} turn={fs.turn}
                showText={!(settings.practice.hideTextWhileRecording && fs.sub === 'after')} />)}
            </WithMicLevel>
            <FlowTransport rate={st.rate} onRate={st.setRate} sub={fs.sub} onStop={() => act('record')} onSkip={() => act('next')} error={error} hint={st.hint} volume={volume} />
          </>) : (<>
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              <WithMicLevel mic={mic}>{(level) => <CueLine cue={cue} level={level} dots={dots} />}</WithMicLevel>
              {st.mode === 'flow' && fs.phase === 'summary' ? (
                <FlowSummary segments={segments} results={fs.results} skipped={fs.skipped} elapsedS={fs.elapsedS}
                  onPlayPair={(r) => playItems(resultPair(r))} onReplayAll={() => playItems([...fs.results].sort((x, y) => x.idx - y.idx).flatMap(resultPair))}
                  onRunAgain={() => { if (fs.range) startFlow(fs.range.from, fs.range.to) }} onEcho={(i) => void drill('echo', i)} onChorus={(i) => void drill('chorus', i)}
                  onFlagWeakest={flagWeakest} onExportWeakest={exportWeakest}
                  onDone={() => offerExport(flow.clear)} />
              ) : (<>
                {st.mode === 'flow' && <FlowSetup segments={segments} from={range.from} to={range.to} sub={fs.sub} onChange={flow.setForm} onStart={() => act('record')}
                  runs={flowRuns} onReplay={replayRun} />}
                <KaraokeSentence wipe={wipe} text={seg.text} words={seg.words_json} showHanzi={st.textPrefs.hanzi && show} showPinyin={st.textPrefs.pinyin && show} translation={seg.translation} showTranslation={st.textPrefs.translation && show} />
                {!(st.textPrefs.hanzi && show) && wipe && <GhostLine count={spans.length} wipe={wipe} />}
                <TwoTrack segment={seg} refPeaks={refPeaks} refDuration={seg.end_s - seg.start_s} refPlayhead={refHead}
                  youPeaks={youPeaks} youDuration={take?.duration ?? 0} youPlayhead={youHead}
                  onPlayRef={() => act('play')} onPlayYou={() => act('replayYou')} onPlaySyllable={playSyllable}
                  score={take?.score ?? null} scoreHeader={<ScoreHeader score={take?.score} best={seg.best_score} attempts={seg.attempts} />} />
              </>)}
            </div>
            <Transport onAction={act} rate={st.rate} onRate={st.setRate} recording={echo === 'recording'} busy={echo === 'uploading'} flagged={seg.difficulty_flag} hint={st.hint} error={error} recordLabel={recordLabel} volume={volume}
              onFinish={() => offerExport(() => navigate('/library'))} />
          </>)}
        </main>
        {!flowRunning && <Drawer segments={segments} idx={st.idx} open={st.drawerOpen} pendingIds={fs.pending} onJump={goTo} onToggle={st.toggleDrawer}
          onEdit={(i) => openDialog('edit', i)} onSplit={(i) => openDialog('split', i)} onMerge={mergeNext} passages={passages} practised={st.practised} />}
      </div>
      {dialog && segments[dialog.idx] && (
        <EditDialog key={`${dialog.mode}-${segments[dialog.idx].id}`} segment={segments[dialog.idx]} mode={dialog.mode} busy={dialogBusy} error={dialogError}
          onSave={saveEdit} onSplit={splitAt} onClose={() => { if (!dialogBusy) setDialog(null) }} />)}
      {exportPrompt && <SessionExportDialog items={exportPrompt.items} onSent={(s) => usePractice.getState().updateSegment(s)} onClose={closeExport} />}
      {help && <HelpOverlay chorusPasses={settings.practice.chorusPasses} onClose={() => setHelp(false)} />}
    </div>
  )
}
