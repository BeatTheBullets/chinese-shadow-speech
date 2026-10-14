import type { ToneStats } from '../api/types'
import { pct } from '../lib/score'

const T = [0, 1, 2, 3, 4]
// Previous tone × tone (spec §6): sandhi contexts such as 3-3 stand out. Cells with fewer than 5 scores are dimmed.
// `onDrill("p-t")` turns cells with data and both tones 1-4 into buttons (neutral 0 is never a drill focus).
export default function ToneMatrix({ pairs, onDrill }: { pairs: ToneStats['pairs']; onDrill?: (key: string) => void }) {
  const at = new Map(pairs.map((p) => [`${p.prev_tone}-${p.tone}`, p]))
  const cls = (m: number) => (m >= 0.7 ? 'cell-ok' : m >= 0.5 ? 'cell-warn' : 'cell-bad')
  return (
    <table className="text-xs text-center border-separate border-spacing-1">
      <thead><tr><th className="text-fgdim font-normal">prev ↓ · tone →</th>{T.map((t) => <th key={t} className="text-fgdim font-normal w-10">{t}</th>)}</tr></thead>
      <tbody>{T.map((p) => (
        <tr key={p}><th className="text-fgdim font-normal">{p}</th>
          {T.map((t) => {
            const c = at.get(`${p}-${t}`)
            if (!c) return <td key={t} className="cell-neutral border rounded h-8">·</td>
            return <td key={t} title={`after tone ${p}, tone ${t}: ${pct(c.mean)} (n ${c.n})`} className={`${cls(c.mean)} border rounded h-8 ${c.n < 5 ? 'opacity-40' : ''}`}>{onDrill && p >= 1 && t >= 1
              ? <button type="button" aria-label={`Drill tone pair ${p}→${t}`} className="w-full h-full" onClick={() => onDrill(`${p}-${t}`)}>{pct(c.mean)}</button>
              : pct(c.mean)}</td>
          })}
        </tr>))}
      </tbody>
    </table>
  )
}
