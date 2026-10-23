import { Link } from 'react-router-dom'
import type { Score } from '../../api/types'
import { changeText, scoreText } from '../../lib/statsView'
import { TOKENS } from '../../theme/tokens'
import Card from '../../ui/Card'

const R = 34, C = 2 * Math.PI * R

export default function ScoreCard({ title, score, unit, how, to }: { title: string; score: Score; unit: string; how: string; to: string }) {
  const v = score.value
  return (
    <Card notched>
      <Link to={to} className="block p-5 hover:bg-line/20">
        <h2 className="text-fg font-semibold">{title}</h2>
        <div className="flex items-center gap-4 mt-2">
          <svg viewBox="0 0 80 80" className="w-20 h-20 shrink-0" aria-hidden="true">
            <circle cx="40" cy="40" r={R} fill="none" stroke={TOKENS.line} strokeWidth="7" />
            {v != null && v > 0 && <circle cx="40" cy="40" r={R} fill="none" stroke={TOKENS.accent} strokeWidth="7" strokeLinecap="round"
              strokeDasharray={`${Math.min(1, v) * C} ${C}`} transform="rotate(-90 40 40)" />}
            <text data-score x="40" y="48" textAnchor="middle" fontSize="24" fill={TOKENS.fg}>{scoreText(v)}</text>
          </svg>
          <div>
            <p className="text-fg"><span>{changeText(score)}</span> <span className="text-xs text-fgdim">vs last week</span></p>
            <p className="text-xs text-fgdim">{`${score.n} ${unit}`}</p>
          </div>
        </div>
        <p className="text-xs text-fgdim mt-3">{how}</p>
      </Link>
    </Card>
  )
}
