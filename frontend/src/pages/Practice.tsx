import { useEffect, useMemo, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { api } from '../api/client'
import type { Mode, Segment } from '../api/types'
import { ClipPlayer, peaks as peaksOf, playSequence } from '../audio/player'
import { Recorder, toWav16k } from '../audio/recorder'
import { findSilenceEnd } from '../audio/pcm'
import Drawer from '../components/Drawer'
import Sentence from '../components/Sentence'
import TopBar from '../components/TopBar'
import Transport from '../components/Transport'
import TwoTrack from '../components/TwoTrack'
import { echoReducer, type EchoEvent, type EchoState } from '../lib/echo'
import { actionForKey, type Action } from '../lib/keys'
import { usePractice, currentSegment, type LastAttempt } from '../store/practice'
import { useSettings, defaultTextPrefs, type TextPrefs } from '../store/settings'

const MOVE_ON = 'Several tries on this one. Move on and come back later.'
const NO_PENDING = new Set<number>()
const MIN_TAKE_S = 0.2
const LOOP_GAP_MS = 250
const message = (e: unknown) => (e instanceof Error ? e.message : String(e))

// Practice page: Echo mode (Chorus/Flow/Guided arrive in Task 10, drawer actions and Anki export in Task 11).
// Handlers read the stores with getState() so timers and late promises never act on a stale render's values.
export default function Practice() {
  const { id } = useParams()
  const lessonId = Number(id)
  const st = usePractice()
  const settings = useSettings()
  const seg = usePractice(currentSegment)
  const segId = seg?.id
  const player = useMemo(() => new ClipPlayer(), [])
  const ctxRef = useRef<AudioContext | null>(null)
  const recRef = useRef<Recorder | null>(null)
  const recGen = useRef(0)                                // bumping it abandons the recording in flight
  const capturing = useRef(false)                         // the mic is open and samples are arriving
  const pendingStart = useRef<Promise<void> | null>(null) // a Recorder.start() still waiting (e.g. on the permission prompt)
  const vadTimer = useRef<number | null>(null)
  const seqCtrl = useRef<AbortController | null>(null)    // the reference-then-take playback after a recording
  const loopRef = useRef<{ cell: number; ctrl: AbortController } | null>(null) // a syllable loop in progress
  const recSeg = useRef<Segment | null>(null)             // the sentence the current recording belongs to
  const playId = useRef(0)
  const echoRef = useRef<EchoState>('idle')
  const [echo, setEcho] = useState<EchoState>('idle')
  const dispatch = (e: EchoEvent) => { echoRef.current = echoReducer(echoRef.current, e); setEcho(echoRef.current) }
  const [refPeaks, setRefPeaks] = useState<Float32Array | null>(null)
  const [refHead, setRefHead] = useState<number | null>(null)
  const [youHead, setYouHead] = useState<number | null>(null)
  const [error, setError] = useState('')
  const [loadError, setLoadError] = useState('')
  const [started] = useState(() => Date.now())
  const [elapsed, setElapsed] = useState(0)

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

  // Leaving the page: drop any recording (including one still at the permission prompt), stop audio, close the context.
  useEffect(() => () => {
    recGen.current++
    clearVad()
    if (capturing.current) { recRef.current?.stop(); capturing.current = false }
    stopPlayback()
    usePractice.getState().setRecording(false)
    ctxRef.current?.close().catch(() => {})
    ctxRef.current = null; recRef.current = null
  }, [player]) // eslint-disable-line react-hooks/exhaustive-deps -- unmount-only; clearVad/stopPlayback touch refs and player only

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

  function clearVad() { if (vadTimer.current != null) { clearTimeout(vadTimer.current); vadTimer.current = null } }
  function stopPlayback() {
    seqCtrl.current?.abort(); seqCtrl.current = null
    loopRef.current?.ctrl.abort(); loopRef.current = null
    player.stop()
  }
  const busy = () => echoRef.current === 'recording' || echoRef.current === 'uploading'

  // Abandons whatever is in flight (recording, pending mic prompt, playback) and returns Echo to idle.
  function cancelActivity() {
    recGen.current++
    clearVad()
    if (capturing.current) { recRef.current?.stop(); capturing.current = false }
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

  // Opens the mic and starts capturing (no VAD). Resolves to null if the recording was abandoned meanwhile;
  // a recorder that starts after that is stopped at once so the mic is not left open. Throws a readable error.
  async function startCapture(): Promise<Recorder | null> {
    const gen = ++recGen.current
    // Recorder.start() is not re-entrant: let an abandoned start (still at the permission prompt) settle first.
    while (pendingStart.current) await pendingStart.current
    if (gen !== recGen.current) return null
    ctxRef.current ??= new AudioContext()
    recRef.current ??= new Recorder(ctxRef.current)
    const rec = recRef.current
    const starting = rec.start()
    const settled = starting.then(() => {}, () => {})
    pendingStart.current = settled
    try { await starting } catch (e) { if (gen !== recGen.current) return null; throw e } finally { if (pendingStart.current === settled) pendingStart.current = null }
    if (gen !== recGen.current) { rec.stop(); return null }
    capturing.current = true
    return rec
  }

  async function startRecording() {
    const s = currentSegment(usePractice.getState())
    if (!s || busy()) return
    stopPlayback()
    recSeg.current = s
    dispatch('RECORD'); usePractice.getState().setRecording(true); setError('')
    try {
      const rec = await startCapture()
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
    if (!capturing.current) { cancelActivity(); return } // still at the permission prompt: abandon it
    clearVad()
    dispatch('STOP')
    const s = recSeg.current
    recSeg.current = null
    await finishRecording('echo', s)
  }

  // Stops capture, keeps the take as the last attempt, uploads it and plays reference then take back to back.
  // `s` is the sentence the recording started on: the take always uploads there.
  async function finishRecording(mode: Mode, s: Segment | null) {
    const ps = usePractice.getState()
    const rec = recRef.current
    capturing.current = false
    ps.setRecording(false)
    if (!s || !rec) { dispatch('CANCEL'); return }
    const samples = rec.stop()
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
    try {
      await playSequence(player, [{ url: api.segments.audioUrl(s.id), rate: ps.rate, onTime: setRefHead }, { url, rate: 1, onTime: setYouHead }], 250, ctrl.signal)
    } catch (e) {
      if (!ctrl.signal.aborted) setError(`Playback failed: ${message(e)}`)
    } finally {
      if (seqCtrl.current === ctrl) seqCtrl.current = null
      if (echoRef.current === 'playback') dispatch('PLAYBACK_DONE')
    }
    await upload
  }

  function playSolo(play: () => Promise<void>) {
    if (busy()) return
    stopPlayback()
    play().catch((e) => setError(`Could not play: ${message(e)}`))
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
    const gap = () => new Promise<void>((resolve) => {
      const onAbort = () => { clearTimeout(t); resolve() }
      const t = setTimeout(() => { ctrl.signal.removeEventListener('abort', onAbort); resolve() }, LOOP_GAP_MS)
      ctrl.signal.addEventListener('abort', onAbort, { once: true })
    })
    void (async () => {
      try {
        while (!ctrl.signal.aborted) {
          await player.playRange(url, ps.rate, from, to, setRefHead)
          if (!ctrl.signal.aborted) await gap()
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

  function act(a: Action) {
    const ps = usePractice.getState()
    if (ps.lesson?.id !== lessonId) return // the store still holds another lesson (this one is loading)
    const savePrefs = (p: TextPrefs) => { ps.setTextPrefs(p); useSettings.getState().setTextPrefs(lessonId, p) }
    const prefs = ps.textPrefs
    switch (a) {
      case 'play': void playRef(); return
      case 'record': void (echoRef.current === 'recording' ? stopRecording() : startRecording()); return
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
      default: return // chorus, exportAnki: Tasks 10 and 11
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
  const hide = st.recordingNow && settings.practice.hideTextWhileRecording
  return (
    <div className="h-full flex flex-col">
      <TopBar title={st.lesson.title} speaker={st.lesson.speaker} idx={st.idx} total={st.lesson.segments.length} mode={st.mode}
        onMode={(m) => { cancelActivity(); st.setMode(m) }} elapsedS={elapsed} />
      <div className="flex-1 flex min-h-0">
        <main className="flex-1 flex flex-col min-w-0">
          <div className="flex-1 overflow-y-auto p-6 space-y-6">
            <Sentence text={seg.text} words={seg.words_json} showHanzi={st.textPrefs.hanzi && !hide} showPinyin={st.textPrefs.pinyin && !hide} translation={seg.translation} showTranslation={st.textPrefs.translation && !hide} />
            <TwoTrack segment={seg} refPeaks={refPeaks} refDuration={seg.end_s - seg.start_s} refPlayhead={refHead}
              youPeaks={st.lastAttempt?.peaks ?? null} youDuration={st.lastAttempt?.duration ?? 0} youPlayhead={youHead}
              onPlayRef={() => act('play')} onPlayYou={() => act('replayYou')} onLoopSyllable={loopSyllable} />
          </div>
          <Transport onAction={act} rate={st.rate} onRate={st.setRate} recording={echo === 'recording'} busy={echo === 'uploading'} flagged={seg.difficulty_flag} hint={st.hint} error={error} />
        </main>
        <Drawer segments={st.lesson.segments} idx={st.idx} open={st.drawerOpen} pendingIds={NO_PENDING} onJump={goTo} onToggle={st.toggleDrawer} />
      </div>
    </div>
  )
}
