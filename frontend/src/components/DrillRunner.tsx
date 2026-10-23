import { useEffect, useMemo, useRef, useState } from 'react'
import { api, ApiError } from '../api/client'
import type { DrillItem, DrillSession, Score, Segment } from '../api/types'
import { playClip } from '../audio/abortable'
import { findSilenceEnd } from '../audio/pcm'
import { ClipPlayer, peaks as peaksOf, playSequence, type SequenceItem } from '../audio/player'
import { toWav16k } from '../audio/recorder'
import { useMic } from '../audio/useMic'
import type { Stage } from '../lib/cue'
import { advance, listened, MAX_TRIES, scored, skip, startDrill, targetsGreen, type DrillState } from '../lib/drill'
import { MIN_TAKE_S } from '../lib/echo'
import { clipSpans, stageWipe } from '../lib/karaoke'
import { actionForKey, type Action } from '../lib/keys'
import { applyAttempt, noticeText, warningText } from '../lib/score'
import { speechBounds } from '../lib/speech'
import { clamp01, playbackVolume } from '../lib/volume'
import { defaultTextPrefs, useSettings, type TextPrefs } from '../store/settings'
import { TOKENS } from '../theme/tokens'
import Button from '../ui/Button'
import KaraokeSentence from './KaraokeSentence'
import LiveWave from './LiveWave'
import ScoreHeader from './ScoreHeader'
import SentenceTools from './SentenceTools'
import type { SoundControls } from './SoundPopover'
import StageState from './StageState'
import Transport from './Transport'
import TwoTrack from './TwoTrack'

const message = (e: unknown) => (e instanceof Error ? e.message : String(e))
const readable = (e: unknown) => (e instanceof ApiError ? e.detail : message(e))

const DRILL_KEYS: Action[] = ['record', 'next', 'replayYou', 'play', 'speed075', 'flag', 'toggleHanzi', 'togglePinyin', 'toggleTranslation']
const TOGGLE: Record<keyof TextPrefs, Action> = { hanzi: 'toggleHanzi', pinyin: 'togglePinyin', translation: 'toggleTranslation' }

// This visit's take of the current sentence; `score` arrives with the upload (undefined until then).
interface DrillTake { url: string; duration: number; peaks: Float32Array; score?: Score | null }

// `playback`: the take's reference-then-you playback is running; `scoring`: its upload has not answered yet.
// The stage (the same as Echo's, spec §8: listen, then "Your turn" with the record frame) and its small note.
function drillStage(st: DrillState, recording: boolean, playback: boolean, scoring: boolean, green: boolean, saving: boolean): { stage: Stage; note?: string } {
  if (saving) return { stage: 'idle', note: 'Saving your take…' }
  if (st.step === 'listen') return { stage: 'listen', note: 'Speak along with it' }
  if (recording) return { stage: 'yourTurn' }
  const stage = playback ? 'review' : 'idle'
  if (st.step === 'review') {
    if (st.outcome === 'retry') return { stage, note: 'Not green yet — Enter to try again' }
    return { stage, note: green ? 'Green — Enter for the next sentence' : 'Enter for the next sentence' }
  }
  if (playback) return { stage }
  if (scoring) return { stage, note: 'Scoring…' }
  return { stage, note: 'Your turn — Enter to record' }
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
  const [recAt, setRecAt] = useState(0)                    // performance-clock second the take began: the stage's timer (it ticks itself)
  const setUploading = (id: number) => { uploadRef.current = id; setUploadingState(id !== 0) }
  const takeNo = useRef(0)
  // Uploads not answered yet, of any sentence: finishing waits for them so the summary has every take.
  const inflight = useRef(new Set<Promise<unknown>>())
  const [saving, setSaving] = useState(false)
  const vadTimer = useRef<number | null>(null)            // the auto-stop's silence check while recording
  const seqCtrl = useRef<AbortController | null>(null)   // the playback in flight (listen clip, reference then take, replays)
  const [refPeaks, setRefPeaks] = useState<Float32Array | null>(null)
  const [refHead, setRefHead] = useState<number | null>(null)
  const [youHead, setYouHead] = useState<number | null>(null)
  const [hint, setHint] = useState('')
  const [error, setError] = useState('')
  // The drill's own speed (S, the Sound pop-up) and text toggles (T/P/E): they start fresh each run and are not a
  // lesson's saved preferences.
  const rateRef = useRef(1)
  const [rate, setRateState] = useState(1)
  const setRate = (r: number) => { rateRef.current = r; setRateState(r) }
  const [prefs, setPrefs] = useState<TextPrefs>(defaultTextPrefs)
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
      clearVad(); seqCtrl.current?.abort(); player.stop()
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
    playClip(player, api.segments.audioUrl(session.items[listenOn].segment.id), rateRef.current, ctrl.signal, setRefHead)
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
  function cancelActivity() { clearVad(); stopPlayback(); mic.abandon(); setRecording(false) }

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
    setRecording(true); setRecAt(performance.now() / 1000)
    try {
      const rec = await mic.open()
      if (!rec) return
      // Stop after 1.2 s of silence following speech, as Echo does (Enter still stops it early)
      const tick = () => {
        vadTimer.current = null
        if (findSilenceEnd(rec.snapshot(), rec.sampleRate) != null) void stopRecording()
        else vadTimer.current = window.setTimeout(tick, 200)
      }
      vadTimer.current = window.setTimeout(tick, 400)
    } catch (e) { setRecording(false); setError(`Microphone unavailable: ${message(e)}`) }
  }

  function clearVad() { if (vadTimer.current != null) { clearTimeout(vadTimer.current); vadTimer.current = null } }

  async function stopRecording() {
    clearVad()
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
    const peaks = peaksOf(got.samples, 400)
    setTake({ url, duration, peaks }); setHint('')
    const mine = ++takeNo.current
    setUploading(mine)
    const ctrl = new AbortController()
    // The take counts once scored: a gate warning costs no try. A failed upload (e.g. 409 while the lesson rebuilds)
    // leaves the run at record with the take still playable. A dropped take (the gates rejected it and the server
    // kept nothing) is a gated one with no take left: its playback stops, it is no attempt and has nothing to replay.
    const upload = api.segments.postAttempt(it.segment.id, wav, { mode: 'drill', drill_session_id: session.id })
      .then((a) => {
        if (!alive.current || finished.current || stRef.current.i !== i) return
        const sc = a.score_json
        if (a.dropped || a.id == null) {
          if (seqCtrl.current === ctrl) stopPlayback()
          if (takeRef.current?.url === url) setTake(null)
        } else {
          if (takeRef.current?.url === url) setTake({ ...takeRef.current, score: sc })
          setSegs((ss) => ss.map((s) => (s.id === it.segment.id ? applyAttempt(s, sc?.overall) : s)))
        }
        setHint(warningText(sc) ?? noticeText(sc) ?? '')
        setSt(scored(stRef.current, { gated: sc?.overall == null, allGreen: targetsGreen(sc, it.targets, session.kind) }, maxTries))
      })
      .catch((e) => { if (alive.current && stRef.current.i === i) setError(`Upload failed: ${readable(e)}`) })
      .finally(() => { inflight.current.delete(upload); if (alive.current && uploadRef.current === mine) setUploading(0) })
    inflight.current.add(upload)
    seqCtrl.current = ctrl
    setPlayback(true)
    try {
      // The take plays from its voice to its end (Task 14); the You track still shows all of it.
      const voice = speechBounds(peaks, duration) ?? {}
      await playSequence(player, [{ url: api.segments.audioUrl(it.segment.id), rate: rateRef.current, onTime: setRefHead }, { url, rate: 1, onTime: setYouHead, ...voice }], 250, ctrl.signal)
    } catch (e) {
      if (!ctrl.signal.aborted) setError(`Playback failed: ${message(e)}`)
    } finally {
      if (seqCtrl.current === ctrl) seqCtrl.current = null
      if (alive.current && takeNo.current === mine) setPlayback(false)
    }
    await upload
  }

  // `rate`: the reference plays at the drill's speed, the user's take always at 1.
  function playSolo(url: string, onTime: (t: number) => void, from?: number, to?: number, rate = 1) {
    if (recRef.current || stRef.current.step === 'listen') return
    stopPlayback()
    const p = from == null ? player.play(url, rate, onTime) : player.playRange(url, rate, from, to ?? from, onTime)
    p.catch((e) => setError(`Could not play: ${message(e)}`))
  }
  const playRef = () => { const s = segRef.current; if (s) playSolo(api.segments.audioUrl(s.id), setRefHead, undefined, undefined, rateRef.current) }
  // The take from its voice to its end; with no clear voice in its waveform, all of it.
  const replayYou = () => {
    const t = takeRef.current, voice = t && speechBounds(t.peaks, t.duration)
    if (t) playSolo(t.url, setYouHead, voice?.from, voice?.to)
  }
  // One syllable of the user's take, as a range of it (usr_contour spans are already on the raw take's timeline). Every
  // syllable has a span, but a missing or unvoiced one has nothing of the user's to play: null.
  function youSyllable(cell: number) {
    const t = takeRef.current, span = t?.score?.usr_contour?.spans[cell]
    const status = t?.score?.syllables[cell]?.status
    return t && span && status !== 'missing' && status !== 'unvoiced' ? { url: t.url, rate: 1, from: span[0], to: span[1] } : null
  }
  // One syllable of the reference at the drill's speed (alignment times are source-absolute; the clip starts at start_s).
  function refSyllable(cell: number) {
    const s = segRef.current, span = s?.ref_alignment_json?.[cell]
    return s && span ? { url: api.segments.audioUrl(s.id, 'wav'), rate: rateRef.current, from: Math.max(0, span.start - s.start_s), to: Math.max(0, span.end - s.start_s) } : null
  }
  function playYouSyllable(cell: number) {
    const y = youSyllable(cell)
    if (y) playSolo(y.url, setYouHead, y.from, y.to)
  }
  // From a click on its character on the sentence card or its verdict cell's ▶.
  function playSyllable(cell: number) {
    const r = refSyllable(cell)
    if (r) playSolo(r.url, setRefHead, r.from, r.to, r.rate)
  }
  // A verdict cell's character: the speaker's syllable, the usual pause, then the user's (the speaker's alone when the
  // user has none there). Same gate as playSolo; a later play or stop ends it.
  function compareSyllable(cell: number) {
    if (recRef.current || stRef.current.step === 'listen') return
    const r = refSyllable(cell), y = youSyllable(cell)
    const items: SequenceItem[] = [...(r ? [{ ...r, onTime: setRefHead }] : []), ...(y ? [{ ...y, onTime: setYouHead }] : [])]
    if (!items.length) return
    stopPlayback()
    const ctrl = new AbortController()
    seqCtrl.current = ctrl
    playSequence(player, items, 250, ctrl.signal)
      .catch((e) => { if (!ctrl.signal.aborted) setError(`Could not play: ${message(e)}`) })
      .finally(() => { if (seqCtrl.current === ctrl) seqCtrl.current = null })
  }

  // ⚑ Difficult, patched on the sentence as Practice does; the run's copy follows.
  function flag() {
    const s = segRef.current
    if (!s) return
    api.segments.patch(s.id, { difficulty_flag: !s.difficulty_flag })
      .then((u) => { if (alive.current) setSegs((ss) => ss.map((x) => (x.id === u.id ? { ...x, difficulty_flag: u.difficulty_flag } : x))) })
      .catch((e) => { if (alive.current) setError(`Could not flag: ${readable(e)}`) })
  }

  // Enter: skip the listening ahead to recording, start/stop a take, then Again or Next. → skips at any time.
  // The other keys do what they do in Practice: Space, R, S, F, T/P/E.
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
      case 'speed075': setRate(rateRef.current === 0.75 ? 1 : 0.75); return
      case 'flag': flag(); return
      case 'toggleHanzi': setPrefs((p) => ({ ...p, hanzi: !p.hanzi })); return
      case 'togglePinyin': setPrefs((p) => ({ ...p, pinyin: !p.pinyin })); return
      case 'toggleTranslation': setPrefs((p) => ({ ...p, translation: !p.translation })); return
      default: return
    }
  }
  const actRef = useRef(act)
  actRef.current = act
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented) return
      const a = actionForKey(e)
      if (!a || !DRILL_KEYS.includes(a)) return
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
  const { wipe } = stageWipe({ spans, refPlaying: st.step === 'listen' || playback, refHead, turnStart: null, now: 0, rate })
  const sound: SoundControls = { rate, onRate: setRate, volume: {
    reference: settings.referenceVolume, guide: settings.guideLevel,
    onReference: (v) => settings.set({ referenceVolume: clamp01(v) }), onGuide: (v) => settings.set({ guideLevel: clamp01(v) }),
  } }
  // What Enter does when not recording: record (now, again) or go on to the next sentence.
  const stage = drillStage(st, recording, playback, uploading, green, saving)
  const enterLabel = st.step === 'listen' ? 'Record now' : st.step === 'review' ? (st.outcome === 'retry' ? 'Again' : 'Next') : undefined
  const tools = <SentenceTools flagged={seg.difficulty_flag} onFlag={() => act('flag')} prefs={prefs} onToggle={(k) => act(TOGGLE[k])} />
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-4 text-sm text-fgdim border-b border-line pb-2">
        <span className="text-fg">{session.label}</span>
        <span>Try {tryNo} / {maxTries}</span>
        <span>{item.lesson_title}</span>
        <span className="ml-auto"><Button label="Finish drill" onClick={finish} /></span>
      </div>
      <StageState slim {...stage} startedAt={recAt} autoStop wave={<LiveWave mic={mic} color={TOKENS.you} />}>
        <KaraokeSentence wipe={wipe} onSyllableClick={playSyllable} text={seg.text} words={seg.words_json} showHanzi={prefs.hanzi && show} showPinyin={prefs.pinyin && show}
          translation={seg.translation} showTranslation={prefs.translation && show} tools={tools} />
      </StageState>
      <TwoTrack segment={seg} refPeaks={refPeaks} refDuration={seg.end_s - seg.start_s} refPlayhead={refHead}
        youPeaks={take?.peaks ?? null} youDuration={take?.duration ?? 0} youPlayhead={youHead}
        onPlayRef={playRef} onPlayYou={replayYou} highlight={item.targets}
        onPlaySyllable={playSyllable} onPlayYouSyllable={playYouSyllable} onCompareSyllable={compareSyllable}
        score={take?.score ?? null} scoreHeader={<ScoreHeader score={take?.score} best={seg.best_score} attempts={seg.attempts} />} />
      {/* The Practice bar, minus Anki: position n / N with › skipping (no going back), Listen, Record (Again when
          reviewing; Next goes on, in accent), Me, Sound. Record pulses while the step waits for a take. */}
      <Transport onAction={act} idx={st.i} total={st.n} recording={recording} busy={uploading && st.step === 'record'} hint={hint} error={error}
        recordLabel={enterLabel} advance={st.step === 'review' && st.outcome !== 'retry'}
        pulse={st.step === 'record' && !recording && !playback && !uploading && !saving ? 'record' : undefined}
        canPrev={false} showAnki={false} sound={sound} />
    </div>
  )
}
