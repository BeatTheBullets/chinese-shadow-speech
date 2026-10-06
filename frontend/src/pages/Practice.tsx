import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Mode, Segment } from '../api/types'
import { playClip, sleep } from '../audio/abortable'
import { findSilenceEnd, sliceSamples } from '../audio/pcm'
import { ClipPlayer, peaks as peaksOf, playSequence } from '../audio/player'
import { toWav16k } from '../audio/recorder'
import { useMic } from '../audio/useMic'
import Drawer from '../components/Drawer'
import FlowSummary from '../components/FlowSummary'
import FlowView, { FlowSetup, FlowTransport } from '../components/FlowView'
import Sentence from '../components/Sentence'
import TopBar from '../components/TopBar'
import Transport from '../components/Transport'
import TwoTrack from '../components/TwoTrack'
import { echoReducer, MIN_TAKE_S, type EchoEvent, type EchoState } from '../lib/echo'
import { weakestResults, type FlowResult } from '../lib/flow'
import { guidedText, nextGuidedStep, type GuidedStep } from '../lib/guided'
import { actionForKey, type Action } from '../lib/keys'
import { usePractice, currentSegment, type LastAttempt } from '../store/practice'
import { useSettings, defaultTextPrefs, type TextPrefs } from '../store/settings'
import { useFlow } from './useFlow'

const MOVE_ON = 'Several tries on this one. Move on and come back later.'
const LOOP_GAP_MS = 250
const CHORUS_GAP_MS = 300  // between chorus passes (§6)
const CHORUS_TAIL_MS = 300 // the chorus take runs this long past the end of the last pass
const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// A multi-step run in progress. Aborting its controller (stop, mode switch, navigation, unmount) ends it.
type RunKind = 'chorus' | 'flow' | 'guided'

// Practice page: Echo, Chorus, Flow and Guided modes (drawer actions and Anki export arrive in Task 11).
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
  const vadTimer = useRef<number | null>(null)
  const seqCtrl = useRef<AbortController | null>(null)    // a playback sequence (reference then take, Flow replays)
  const loopRef = useRef<{ cell: number; ctrl: AbortController } | null>(null) // a syllable loop in progress
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
  const flow = useFlow({ lessonId, player, mic, beginRun: () => beginRun('flow'), endRun, setError })

  useEffect(() => { const t = setInterval(() => setElapsed((Date.now() - started) / 1000), 1000); return () => clearInterval(t) }, [started])

  useEffect(() => {
    let cancelled = false
    setLoadError('')
    api.lessons.get(lessonId).then((l) => {
      if (cancelled) return
      const ps = usePractice.getState(), s = useSettings.getState()
      ps.setLesson(l); ps.setTextPrefs(s.textPrefs[String(lessonId)] ?? defaultTextPrefs); ps.setRate(s.practice.defaultRate)
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

  useEffect(() => {
    if (segId == null) return
    let cancelled = false
    const url = api.segments.audioUrl(segId)
    void player.preload(url)
    setRefPeaks(null); setRefHead(null); setYouHead(null)
    player.peaksFor(url, 400).then((p) => { if (!cancelled) setRefPeaks(p) }).catch(() => {})
    const ps = usePractice.getState(); const nxt = ps.lesson?.segments[ps.idx + 1]
    if (nxt) void player.preload(api.segments.audioUrl(nxt.id))
    return () => { cancelled = true }
  }, [segId, player])

  // Guided starts over on every new sentence and mode.
  useEffect(() => { setGuided('listen') }, [segId, st.mode])

  function beginRun(kind: RunKind): AbortController {
    const ctrl = new AbortController()
    runRef.current = { kind, ctrl }; setRunKind(kind)
    return ctrl
  }
  function endRun(ctrl: AbortController) { if (runRef.current?.ctrl === ctrl) { runRef.current = null; setRunKind(null) } }
  function abortRun() { const r = runRef.current; if (!r) return; runRef.current = null; setRunKind(null); r.ctrl.abort() }
  function clearVad() { if (vadTimer.current != null) { clearTimeout(vadTimer.current); vadTimer.current = null } }
  function stopPlayback() {
    seqCtrl.current?.abort(); seqCtrl.current = null
    loopRef.current?.ctrl.abort(); loopRef.current = null
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
    stopPlayback()
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
    // The store moved to another sentence meanwhile (e.g. the lesson reloaded): save the take, skip the playback.
    if (currentSegment(ps)?.id !== s.id) {
      dispatch('CANCEL')
      api.segments.postAttempt(s.id, wav, { session_id: ps.sessionId ?? undefined, mode }).catch((e) => setError(`Upload failed: ${message(e)}`))
      return
    }
    const url = URL.createObjectURL(wav)
    const take: LastAttempt = { id: 0, url, duration, peaks: peaksOf(samples, 400) }
    ps.setLastAttempt(take); ps.bumpAttempts()
    if (usePractice.getState().attemptsThisSegment >= useSettings.getState().practice.moveOnAfter) ps.setHint(MOVE_ON)
    const upload = api.segments.postAttempt(s.id, wav, { session_id: ps.sessionId ?? undefined, mode })
      .then((a) => { const cur = usePractice.getState(); if (cur.lastAttempt?.url === url) cur.setLastAttempt({ ...take, id: a.id }) })
      .catch((e) => setError(`Upload failed: ${message(e)}`))
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
    stopPlayback(); setError('')
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
  function replayYou() {
    const take = usePractice.getState().lastAttempt
    if (take) playSolo(() => player.play(take.url, 1, setYouHead))
  }
  // Loops one syllable of the reference until any other action; clicking the same cell again stops it.
  // Alignment times are source-absolute, the clip starts at seg.start_s.
  function loopSyllable(cell: number) {
    if (busy()) return
    const same = loopRef.current?.cell === cell
    stopPlayback()
    if (same) return
    const ps = usePractice.getState(), s = currentSegment(ps), span = s?.ref_alignment_json?.[cell]
    if (!s || !span) return
    const ctrl = new AbortController()
    loopRef.current = { cell, ctrl }
    const url = api.segments.audioUrl(s.id, 'wav'), from = Math.max(0, span.start - s.start_s), to = Math.max(0, span.end - s.start_s)
    void (async () => {
      try {
        while (!ctrl.signal.aborted) {
          await player.playRange(url, ps.rate, from, to, setRefHead)
          await sleep(LOOP_GAP_MS, ctrl.signal)
        }
      } catch (e) {
        if (!ctrl.signal.aborted) setError(`Could not play: ${message(e)}`)
      } finally {
        if (loopRef.current?.ctrl === ctrl) loopRef.current = null
      }
    })()
  }

  function goTo(i: number) {
    const ps = usePractice.getState(), n = ps.lesson?.segments.length ?? 0
    const j = Math.max(0, Math.min(n - 1, i))
    if (n === 0 || j === ps.idx) return
    cancelActivity()
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

  // Flow: the setup form's range, defaulting to the current sentence through the last.
  function flowRange() {
    const ps = usePractice.getState(), last = (ps.lesson?.segments.length ?? 1) - 1
    const clamp = (i: number) => Math.max(0, Math.min(last, i))
    const from = clamp(flow.state.from ?? ps.idx), to = clamp(flow.state.to ?? last)
    return { from: Math.min(from, to), to: Math.max(from, to) }
  }
  function startFlow(from: number, to: number) {
    cancelActivity()
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
      api.segments.patch(r.segmentId, { difficulty_flag: true }).then(usePractice.getState().updateSegment).catch((e) => setError(`Could not flag: ${message(e)}`))
    }
  }
  const pairOf = (r: FlowResult) => [{ url: api.segments.audioUrl(r.segmentId), rate: usePractice.getState().rate }, { url: r.url, rate: 1 }]

  function act(a: Action) {
    const ps = usePractice.getState()
    if (ps.lesson?.id !== lessonId) return // the store still holds another lesson (this one is loading)
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
        if (s) api.segments.patch(s.id, { difficulty_flag: !s.difficulty_flag }).then(usePractice.getState().updateSegment).catch((e) => setError(`Could not flag: ${message(e)}`))
        return
      }
      default: return // exportAnki: Task 11
    }
  }
  const actRef = useRef(act)
  actRef.current = act
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
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
  const hide = st.recordingNow && settings.practice.hideTextWhileRecording
  const show = !hide && (st.mode !== 'guided' || guidedText(guided).showText)
  const fs = flow.state
  const flowRunning = fs.phase === 'running'
  const recordLabel = runKind === 'chorus' || runKind === 'guided' ? '■ stop'
    : st.mode === 'chorus' ? `● Chorus ×${settings.practice.chorusPasses}`
    : st.mode === 'guided' ? `● ${guidedText(guided).label}`
    : st.mode === 'flow' ? '● Start flow' : undefined
  const range = flowRange()
  return (
    <div className="h-full flex flex-col">
      <TopBar title={st.lesson.title} speaker={st.lesson.speaker} idx={flowRunning ? fs.current : st.idx} total={segments.length} mode={st.mode}
        onMode={(m) => void switchMode(m)} elapsedS={elapsed} />
      <div className="flex-1 flex min-h-0">
        <main className="flex-1 flex flex-col min-w-0">
          {flowRunning ? (<>
            <FlowView segments={segments} current={fs.current} pending={fs.pending} micPeak={fs.micPeak} sub={fs.sub}
              showText={!(settings.practice.hideTextWhileRecording && fs.sub === 'after')} />
            <FlowTransport rate={st.rate} onRate={st.setRate} sub={fs.sub} onStop={() => act('record')} onSkip={() => act('next')} error={error} />
          </>) : (<>
            <div className="flex-1 overflow-y-auto p-6 space-y-6">
              {st.mode === 'flow' && fs.phase === 'summary' ? (
                <FlowSummary segments={segments} results={fs.results} skipped={fs.skipped} elapsedS={fs.elapsedS}
                  onPlayPair={(r) => playItems(pairOf(r))} onReplayAll={() => playItems([...fs.results].sort((x, y) => x.idx - y.idx).flatMap(pairOf))}
                  onRunAgain={() => { if (fs.range) startFlow(fs.range.from, fs.range.to) }} onEcho={(i) => void drill('echo', i)} onChorus={(i) => void drill('chorus', i)}
                  onFlagWeakest={flagWeakest} onExportWeakest={() => { /* TODO(Task 11): send the weakest three to Anki with exportToAnki */ }}
                  onDone={flow.clear} />
              ) : (<>
                {st.mode === 'flow' && <FlowSetup segments={segments} from={range.from} to={range.to} sub={fs.sub} onChange={flow.setForm} onStart={() => act('record')} />}
                <Sentence text={seg.text} words={seg.words_json} showHanzi={st.textPrefs.hanzi && show} showPinyin={st.textPrefs.pinyin && show} translation={seg.translation} showTranslation={st.textPrefs.translation && show} />
                <TwoTrack segment={seg} refPeaks={refPeaks} refDuration={seg.end_s - seg.start_s} refPlayhead={refHead}
                  youPeaks={st.lastAttempt?.peaks ?? null} youDuration={st.lastAttempt?.duration ?? 0} youPlayhead={youHead}
                  onPlayRef={() => act('play')} onPlayYou={() => act('replayYou')} onLoopSyllable={loopSyllable} />
              </>)}
            </div>
            <Transport onAction={act} rate={st.rate} onRate={st.setRate} recording={echo === 'recording'} busy={echo === 'uploading'} flagged={seg.difficulty_flag} hint={st.hint} error={error} recordLabel={recordLabel} />
          </>)}
        </main>
        {!flowRunning && <Drawer segments={segments} idx={st.idx} open={st.drawerOpen} pendingIds={fs.pending} onJump={goTo} onToggle={st.toggleDrawer} />}
      </div>
    </div>
  )
}
