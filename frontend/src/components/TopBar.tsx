import { Link } from 'react-router-dom'
import type { Mode } from '../api/types'
export default function TopBar({ title, speaker, idx, total, mode, onMode, elapsedS }: { title: string; speaker: string; idx: number; total: number; mode: Mode; onMode: (m: Mode) => void; elapsedS: number }) {
  const mm = String(Math.floor(elapsedS / 60)).padStart(2, '0'), ss = String(Math.floor(elapsedS % 60)).padStart(2, '0')
  return (
    <div className="flex items-center justify-between px-4 py-2 border-b border-line text-sm text-fgdim">
      <span><Link to="/library" className="mr-3 hover:text-fghi" title="Back to the library">←</Link>
        <span className="font-hanzi text-fghi">{speaker && `${speaker} · `}{title}</span> &nbsp; {idx + 1} / {total}</span>
      <span className="flex gap-1">{(['echo', 'chorus', 'flow', 'guided'] as Mode[]).map((m) => (
        <button key={m} onClick={() => onMode(m)} className={`px-2 py-0.5 rounded border ${m === mode ? 'bg-[#1c2a3a] border-accent text-white' : 'border-line'}`}>{m[0].toUpperCase() + m.slice(1)}</button>))}</span>
      <span className={elapsedS >= 1200 ? 'text-warn' : ''} title="Session time">⏱ {mm}:{ss}</span>
    </div>
  )
}
