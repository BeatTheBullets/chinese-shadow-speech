import { useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { DrillItem, DrillSession, Score, Segment } from '../api/types'
import { playClip } from '../audio/abortable'
import { ClipPlayer, peaks as peaksOf, playSequence } from '../audio/player'
import { toWav16k } from '../audio/recorder'
import { useMic } from '../audio/useMic'
import type { Cue } from '../lib/cue'
import { advance, listened, MAX_TRIES, scored, skip, startDrill, targetsGreen, type DrillState } from '../lib/drill'
import { MIN_TAKE_S } from '../lib/echo'
import { clipSpans, stageWipe } from '../lib/karaoke'
import { actionForKey, type Action } from '../lib/keys'
import { applyAttempt, noticeText, warningText } from '../lib/score'
import { clamp01, playbackVolume } from '../lib/volume'
import { defaultTextPrefs, useSettings } from '../store/settings'
import CueLine, { WithMicLevel } from './CueLine'
import KaraokeSentence from './KaraokeSentence'
import ScoreHeader from './ScoreHeader'
import TwoTrack from './TwoTrack'
import VolumeSliders, { type VolumeControls } from './VolumeSliders'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
const readable = (e: unknown) => (e instanceof ApiError ? e.detail : message(e))

// This visit's take of the current sentence; `score` arrives with the upload (undefined until then).
interface DrillTake { url: string; duration: number; peaks: Float32Array; score?: Score | null }

// `playback`: the take's reference-then-you playback is running; `scoring`: its upload has not answered yet.
function cueOf(st: DrillState, recording: boolean, playback: boolean, scoring: boolean, green: boolean, saving: boolean): Cue {
  if (saving) return { icon: '⏳', text: 'Saving your take…', tone: 'neutral' }
  if (st.step === 'listen') return { icon: '🎧', text: 'Listen and speak along', tone: 'ref' }
  if (recording) return { icon: '🗣', text: 'Your turn — speak now', tone: 'you' }
  if (st.step === 'review') {
    if (st.outcome === 'retry') return { icon: '↻', text: 'Not green yet — Enter to try again', tone: 'you' }
    return green ? { icon: '✓', text: 'Green — Enter for the next sentence', tone: 'ok' } : { icon: '→', text: 'Enter for the next sentence', tone: 'neutral' }
  }
  if (playback) return { icon: '🎧', text: 'Listen — the original, then you', tone: 'ref' }
  if (scoring) return { icon: '⏳', text: 'Scoring…', tone: 'neutral' }
  return { icon: '🗣', text: 'Your turn — Enter to record', tone: 'you' }
}

// One drill run (spec §4): per sentence, listen along once at the guide level, then Echo takes until the target
// syllables are green or the tries run out. The step machine is lib/drill.ts; this owns the audio, mic and uploads.
// Handlers read refs, so late promises and the key listener never act on a stale render's values.
export default function DrillRunner({ session, onFinish }: { session: DrillSession; onFinish: () => void }) {
  const settings = useSettings()
  const player = useMemo(() => new ClipPlayer(), [])
  const mic = useMic()
  const maxTries = session.max_tries ?? MAX_TRIES
  const stRef = useRef<DrillState>(startDrill(session.items.length))
  const [st, setStState] = useState(stRef.current)
  const setSt = (s: DrillState) => { stRef.current = s; setStState(s) }
  // The run's copy of each sentence, so ScoreHeader's best and attempts follow this run's takes.
  const [segs, setSegs] = useState<Segment[]>(() => session.items.map((it) => it.segment))
  const takeRef = useRef<DrillTake | null>(null)
  const [take, setTakeState] = useState<DrillTake | null>(null)
  const setTake = (t: DrillTake | null) => {
    if (takeRef.current && takeRef.current.url !== t?.url) URL.revokeObjectURL(takeRef.current.url)
    takeRef.current = t; setTakeState(t)
  }
  const recRef = useRef(false), uploadRef = useRef(0)    // the mic is open / the take uploading (0: none)
  const [recording, setRecordingState] = useState(false)
  const [uploading, setUploadingState] = useState(false)
  const [playback, setPlayback] = useState(false)          // a take's reference-then-you playback is running
  const setRecording = (v: boolean) => { recRef.current = v; setRecordingState(v) }
  const setUploading = (id: number) => { uploadRef.current = id; setUploadingState(id !== 0) }
  const takeNo = useRef(0)
  // Uploads not answered yet, of any sentence: finishing waits for them so the summary has every take.
  const inflight = useRef(new Set<Promise<unknown>>())
  const [saving, setSaving] = useState(false)
  const seqCtrl = useRef<AbortController | null>(null)   // the playback in flight (listen clip, reference then take, replays)
  const [refPeaks, setRefPeaks] = useState<Float32Array | null>(null)
  const [refHead, setRefHead] = useState<number | null>(null)
  const [youHead, setYouHead] = useState<number | null>(null)
  const [hint, setHint] = useState('')
  const [error, setError] = useState('')
  const alive = useRef(true)
  const finished = useRef(false)

  const item: DrillItem | undefined = session.items[Math.min(st.i, session.items.length - 1)]
  const seg = item ? segs[st.i] ?? item.segment : null
  const segId = seg?.id
  const segRef = useRef(seg)
  segRef.current = seg

  // Leaving mid-drill ends the session (best effort). StrictMode's rehearsal unmount is followed at once by a remount,
  // so the end waits a tick and only goes out if the runner is still gone.
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      seqCtrl.current?.abort(); player.stop()
      setTimeout(() => { if (!alive.current && !finished.current) { finished.current = true; api.drill.end(session.id).catch(() => {}) } }, 0)
    }
  }, [player, session.id])
  useEffect(() => () => { if (takeRef.current) URL.revokeObjectURL(takeRef.current.url) }, [])

  // The reference at the guide level while listening along, else at the reference volume; follows the sliders live.
  // Declared before the listen effect so the level is set before the clip starts.
  useEffect(() => {
    player.setVolume(playbackVolume({ speakingAlong: st.step === 'listen', referenceVolume: settings.referenceVolume, guideLevel: settings.guideLevel }))
  }, [player, st.step, settings.referenceVolume, settings.guideLevel])

  useEffect(() => {
    if (segId == null) return
    let cancelled = false
    const url = api.segments.audioUrl(segId)
    setRefPeaks(null)
    player.peaksFor(url, 400).then((p) => { if (!cancelled) setRefPeaks(p) }).catch(() => {})
    const nxt = session.items[stRef.current.i + 1]
    if (nxt) void player.preload(api.segments.audioUrl(nxt.segment.id))
    return () => { cancelled = true }
  }, [segId, player, session.items])

  // listen: the clip once, the mic closed; when it ends, on to record.
  const listenOn = st.step === 'listen' ? st.i : null
  useEffect(() => {
    if (listenOn == null) return
    const ctrl = new AbortController()
    seqCtrl.current = ctrl
    playClip(player, api.segments.audioUrl(session.items[listenOn].segment.id), 1, ctrl.signal, setRefHead)
      .catch((e) => { if (!ctrl.signal.aborted) setError(`Could not play the reference: ${message(e)}`) })
      .finally(() => {
        if (seqCtrl.current === ctrl) seqCtrl.current = null
        if (!ctrl.signal.aborted && stRef.current.step === 'listen') setSt(listened(stRef.current))
      })
    return () => ctrl.abort()
  }, [listenOn, player, session.items])

  // After the last sentence the run ends by itself.
  useEffect(() => { if (st.step === 'done') finish() }, [st.step]) // eslint-disable-line react-hooks/exhaustive-deps -- finish reads refs only

  function stopPlayback() { seqCtrl.current?.abort(); seqCtrl.current = null; player.stop() }
  // A pending upload carries on (and is ignored once the run has moved to another sentence).
  function cancelActivity() { stopPlayback(); mic.abandon(); setRecording(false) }

  function finish() {
    if (finished.current) return
    finished.current = true
    cancelActivity()
    if (inflight.current.size) setSaving(true)
    // The uploads never reject (they catch their own errors); a failed one still lets the drill end.
    Promise.all([...inflight.current]).then(() => api.drill.end(session.id)).catch(() => {}).finally(() => { if (alive.current) onFinish() })
  }

  // To another sentence (or back to record for a retry): what belongs to the old one goes.
  function moveTo(next: DrillState) {
    const prev = stRef.current
    stopPlayback()
    if (next.i !== prev.i) { setTake(null); setUploading(0); setRefHead(null); setYouHead(null) }
    setHint(''); setError('')
    setSt(next)
    if (next.step === 'record') void startRecording()
  }

  async function startRecording() {
    // Not while the last take uploads: its score decides whether there is another try.
    if (recRef.current || uploadRef.current !== 0 || stRef.current.step !== 'record') return
    stopPlayback(); setError('')
    setRecording(true)
    try { await mic.open() }
    catch (e) { setRecording(false); setError(`Microphone unavailable: ${message(e)}`) }
  }

  async function stopRecording() {
    if (!recRef.current) return
    if (!mic.capturing()) { cancelActivity(); return } // still at the permission prompt: abandon it
    const got = mic.finish()
    setRecording(false)
    if (!got) return
    const duration = got.samples.length / got.rec.sampleRate
    if (duration < MIN_TAKE_S) { setError('Too short to keep, nothing was saved. Try again.'); return }
    const i = stRef.current.i, it = session.items[i]
    const wav = toWav16k(got.samples, got.rec.sampleRate)
    const url = URL.createObjectURL(wav)
    setTake({ url, duration, peaks: peaksOf(got.samples, 400) }); setHint('')
    const mine = ++takeNo.current
    setUploading(mine)
    // The take counts once scored: a gate warning costs no try. A failed upload (e.g. 409 while the lesson rebuilds)
    // leaves the run at record with the take still playable.
    const upload = api.segments.postAttempt(it.segment.id, wav, { mode: 'drill', drill_session_id: session.id })
      .then((a) => {
        if (!alive.current || finished.current || stRef.current.i !== i) return
        const sc = a.score_json
        if (takeRef.current?.url === url) setTake({ ...takeRef.current, score: sc })
        setSegs((ss) => ss.map((s) => (s.id === it.segment.id ? applyAttempt(s, sc?.overall) : s)))
        setHint(warningText(sc) ?? noticeText(sc) ?? '')
        setSt(scored(stRef.current, { gated: sc?.overall == null, allGreen: targetsGreen(sc, it.targets, session.kind) }, maxTries))
      })
      .catch((e) => { if (alive.current && stRef.current.i === i) setError(`Upload failed: ${readable(e)}`) })
      .finally(() => { inflight.current.delete(upload); if (alive.current && uploadRef.current === mine) setUploading(0) })
    inflight.current.add(upload)
    const ctrl = new AbortController()
    seqCtrl.current = ctrl
    setPlayback(true)
    try {
      await playSequence(player, [{ url: api.segments.audioUrl(it.segment.id), rate: 1, onTime: setRefHead }, { url, rate: 1, onTime: setYouHead }], 250, ctrl.signal)
    } catch (e) {
      if (!ctrl.signal.aborted) setError(`Playback failed: ${message(e)}`)
    } finally {
      if (seqCtrl.current === ctrl) seqCtrl.current = null
      if (alive.current && takeNo.current === mine) setPlayback(false)
    }
    await upload
  }

  function playSolo(url: string, onTime: (t: number) => void, from?: number, to?: number) {
    if (recRef.current || stRef.current.step === 'listen') return
    stopPlayback()
    const p = from == null ? player.play(url, 1, onTime) : player.playRange(url, 1, from, to ?? from, onTime)
    p.catch((e) => setError(`Could not play: ${message(e)}`))
  }
  const playRef = () => { const s = segRef.current; if (s) playSolo(api.segments.audioUrl(s.id), setRefHead) }
  const replayYou = () => { const t = takeRef.current; if (t) playSolo(t.url, setYouHead) }
  // One syllable of the reference (alignment times are source-absolute; the clip starts at start_s).
  function playSyllable(cell: number) {
    const s = segRef.current, span = s?.ref_alignment_json?.[cell]
    if (s && span) playSolo(api.segments.audioUrl(s.id, 'wav'), setRefHead, Math.max(0, span.start - s.start_s), Math.max(0, span.end - s.start_s))
  }

  // Enter: skip the listening ahead to recording, start/stop a take, then Again or Next. → skips at any time.
  function act(a: Action) {
    if (finished.current) return
    const s = stRef.current
    switch (a) {
      case 'record':
        if (s.step === 'listen') { moveTo(listened(s)); return }
        if (s.step === 'record') { void (recRef.current ? stopRecording() : startRecording()); return }
        if (s.step === 'review') moveTo(advance(s))
        return
      case 'next': cancelActivity(); moveTo(skip(s)); return
      case 'replayYou': replayYou(); return
      case 'play': playRef(); return
      default: return
    }
  }
  const actRef = useRef(act)
  actRef.current = act
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return
      const a = actionForKey(e)
      if (!a || !['record', 'next', 'replayYou', 'play'].includes(a)) return
      e.preventDefault()
      // The shortcut acts on the page, so a focused button must not also be activated by Space/Enter.
      if (e.target instanceof HTMLElement && e.target !== document.body) e.target.blur()
      actRef.current(a)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  if (!item || !seg) return null
  const green = st.step === 'review' && targetsGreen(take?.score, item.targets, session.kind)
  const tryNo = Math.min(maxTries, st.step === 'review' && take?.score?.overall != null ? st.tries : st.tries + 1)
  const show = !(recording && settings.practice.hideTextWhileRecording)
  const spans = clipSpans(seg.ref_alignment_json, seg.start_s)
  const { wipe } = stageWipe({ spans, refPlaying: st.step === 'listen' || playback, refHead, turnStart: null, now: 0, rate: 1 })
  const volume: VolumeControls = {
    reference: settings.referenceVolume, guide: settings.guideLevel,
    onReference: (v) => settings.set({ referenceVolume: clamp01(v) }), onGuide: (v) => settings.set({ guideLevel: clamp01(v) }),
  }
  const enterLabel = st.step === 'listen' ? 'Record now' : st.step === 'review' ? (st.outcome === 'retry' ? 'Again' : 'Next') : recording ? '■ Stop' : '● Record'
  const b = 'px-3 py-1 rounded bg-panel2 text-sm disabled:opacity-40'
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-4 text-sm text-fgdim border-b border-line pb-2">
        <span className="text-fghi">{session.label}</span>
        <span>Sentence {st.i + 1} / {st.n}</span>
        <span>Try {tryNo} / {maxTries}</span>
        <span>{item.lesson_title}</span>
        <button className="btn ml-auto" onClick={finish}>Finish</button>
      </div>
      <WithMicLevel mic={mic}>{(level) => <CueLine cue={cueOf(st, recording, playback, uploading, green, saving)} level={level} />}</WithMicLevel>
      <KaraokeSentence wipe={wipe} text={seg.text} words={seg.words_json} showHanzi={defaultTextPrefs.hanzi && show} showPinyin={defaultTextPrefs.pinyin && show}
        translation={seg.translation} showTranslation={false} />
      <TwoTrack segment={seg} refPeaks={refPeaks} refDuration={seg.end_s - seg.start_s} refPlayhead={refHead}
        youPeaks={take?.peaks ?? null} youDuration={take?.duration ?? 0} youPlayhead={youHead}
        onPlayRef={playRef} onPlayYou={replayYou} onPlaySyllable={playSyllable} highlight={item.targets}
        score={take?.score ?? null} scoreHeader={<ScoreHeader score={take?.score} best={seg.best_score} attempts={seg.attempts} />} />
      <div className="border-t border-line pt-3 text-center space-y-1">
        <div className="flex justify-center gap-2 items-center">
          <button className={b} onClick={() => act('record')} disabled={uploading && st.step === 'record'}>{enterLabel}</button>
          <button className={b} onClick={() => act('next')} title="Skip to the next sentence (→)">Skip →</button>
          <button className={b} onClick={replayYou} disabled={!take}>▶ R</button>
          <VolumeSliders volume={volume} />
        </div>
        <p className="text-xs text-fgdim">Enter record / stop / next · → skip · R your take · Space the reference</p>
        {hint && <p className="text-xs text-warn">{hint}</p>}
        {error && <p className="text-xs text-bad" role="alert">{error}</p>}
      </div>
    </div>
  )
}
