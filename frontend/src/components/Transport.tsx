import type { Action } from '../lib/keys'
interface Props { onAction: (a: Action) => void; rate: number; onRate: (r: number) => void; recording: boolean; busy: boolean; flagged: boolean; hint: string; error: string }
export default function Transport({ onAction, rate, onRate, recording, busy, flagged, hint, error }: Props) {
  const b = 'px-3 py-1 rounded bg-panel2 text-sm disabled:opacity-40'
  return (
    <div className="border-t border-line p-3 text-center space-y-1">
      <div className="flex justify-center gap-2 items-center">
        <button className={b} onClick={() => onAction('prev')} title="Previous (←)">◀</button>
        <button className={b} onClick={() => onAction('play')} disabled={recording}>▶ Space</button>
        <button className={`${b} ${recording ? 'bg-[#5a1f26] text-[#ffd7db]' : ''}`} onClick={() => onAction('record')} disabled={busy}>{recording ? '■ stop' : '● Enter'}</button>
        <button className={b} onClick={() => onAction('chorus')} disabled={recording || busy}>↻ C</button>
        <button className={b} onClick={() => onAction('replayYou')}>▶ R</button>
        {/* blur after a drag so Space/arrows go back to the page shortcuts instead of the slider */}
        <label className="text-xs text-fgdim flex items-center gap-1">{rate.toFixed(2)}×<input type="range" aria-label="Playback speed" min={0.6} max={1} step={0.05} value={rate}
          onChange={(e) => onRate(Number(e.target.value))} onPointerUp={(e) => e.currentTarget.blur()} /></label>
        <button className={b} onClick={() => onAction('speed075')}>0.75×</button>
        <button className={`${b} ${flagged ? 'text-warn' : ''}`} onClick={() => onAction('flag')}>⚑ F</button>
        <button className={b} onClick={() => onAction('toggleHanzi')}>T</button><button className={b} onClick={() => onAction('togglePinyin')}>P</button><button className={b} onClick={() => onAction('toggleTranslation')}>E</button>
        <button className={b} onClick={() => onAction('exportAnki')}>A → Anki</button>
        <button className={b} onClick={() => onAction('next')} title="Next (→)">▶</button>
      </div>
      {hint && <p className="text-xs text-warn">{hint}</p>}
      {error && <p className="text-xs text-bad" role="alert">{error}</p>}
    </div>
  )
}
