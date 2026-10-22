import type { MouseEvent } from 'react'
import { Link } from 'react-router-dom'
import type { Mode } from '../api/types'
import { mmss } from '../lib/time'
import { MODES, modeHelp, modeName } from '../lib/modeHelp'

export interface PassagePick { index: number; titles: string[]; onPick: (k: number) => void }
interface Props {
  title: string; speaker: string; mode: Mode; onMode: (m: Mode) => void; elapsedS: number
  passage?: PassagePick | null; onHelp: () => void
  onBack?: (e: MouseEvent<HTMLAnchorElement>) => void
}
// Practice's top bar, the same treatment as the Shell's navigation: `panel`, the active mode underlined in accent. The
// sentence position (n / N) lives on the control bar only. ⌂ Library stays a link (a new tab is the browser's, and
// `onBack` may hold it back to offer the session export), dressed as the shared Button through `.btn`.
export default function TopBar({ title, speaker, mode, onMode, elapsedS, passage, onHelp, onBack }: Props) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-4 bg-panel border-b border-line text-sm text-fgdim">
      <span className="flex items-center gap-3 py-2 min-w-0">
        <Link to="/library" onClick={onBack} className="btn hover:border-accent" title="Back to the library" aria-label="Back to the library">⌂ Library</Link>
        <span lang="zh" className="font-hanzi text-fg truncate">{speaker && `${speaker} · `}{title}</span>
        {passage && passage.titles.length > 0 && (
          <label className="flex items-center gap-1 whitespace-nowrap">Passage {Math.max(0, passage.index) + 1} / {passage.titles.length}
            <select aria-label="Go to passage" className="inp max-w-[14rem]" value={Math.max(0, passage.index)}
              onChange={(e) => passage.onPick(Number(e.target.value))}>
              {passage.titles.map((t, k) => <option key={k} value={k}>{t}</option>)}
            </select></label>)}
      </span>
      <span className="flex items-center gap-4">
        {MODES.map((m) => (
          <button key={m} type="button" title={modeHelp(m)} onClick={() => onMode(m)} aria-pressed={m === mode}
            className={`py-2 border-b-2 ${m === mode ? 'border-accent text-fg font-semibold' : 'border-transparent hover:text-fg'}`}>{modeName(m)}</button>))}
        <button type="button" className="ml-1 h-7 w-7 rounded-xl border border-line bg-card text-fg hover:border-accent" aria-label="Help" title="Help (?)" onClick={onHelp}>?</button>
        <span className={`tabular-nums ${elapsedS >= 1200 ? 'text-warn' : ''}`} title="Session time">⏱ {mmss(elapsedS)}</span>
      </span>
    </div>
  )
}
