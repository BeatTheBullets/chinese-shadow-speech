import { Link } from 'react-router-dom'
import type { Mode } from '../api/types'
import { MODES, modeHelp, modeName } from '../lib/modeHelp'

export interface PassagePick { index: number; titles: string[]; onPick: (k: number) => void }
interface Props {
  title: string; speaker: string; idx: number; total: number; mode: Mode; onMode: (m: Mode) => void; elapsedS: number
  passage?: PassagePick | null; chorusPasses: number; onHelp: () => void
}
export default function TopBar({ title, speaker, idx, total, mode, onMode, elapsedS, passage, chorusPasses, onHelp }: Props) {
  const mm = String(Math.floor(elapsedS / 60)).padStart(2, '0'), ss = String(Math.floor(elapsedS % 60)).padStart(2, '0')
  return (
    <div className="flex items-center justify-between px-4 py-2 border-b border-line text-sm text-fgdim">
      <span><Link to="/library" className="mr-3 hover:text-fghi" title="Back to the library">←</Link>
        <span className="font-hanzi text-fghi">{speaker && `${speaker} · `}{title}</span> &nbsp; {idx + 1} / {total}
        {passage && passage.titles.length > 0 && (
          <label className="ml-3">Passage {Math.max(0, passage.index) + 1} / {passage.titles.length}
            <select aria-label="Go to passage" className="ml-1 bg-panel2 rounded px-1 py-0.5 text-fg" value={Math.max(0, passage.index)}
              onChange={(e) => passage.onPick(Number(e.target.value))}>
              {passage.titles.map((t, k) => <option key={k} value={k}>{t}</option>)}
            </select></label>)}</span>
      <span className="flex gap-1">{MODES.map((m) => (
        <button key={m} title={modeHelp(m, chorusPasses)} onClick={() => onMode(m)}
          className={`px-2 py-0.5 rounded border ${m === mode ? 'bg-[#1c2a3a] border-accent text-white' : 'border-line'}`}>{modeName(m)}</button>))}
        <button className="ml-2 px-2 py-0.5 rounded border border-line" aria-label="Help" title="Help (?)" onClick={onHelp}>?</button></span>
      <span className={elapsedS >= 1200 ? 'text-warn' : ''} title="Session time">⏱ {mm}:{ss}</span>
    </div>
  )
}
