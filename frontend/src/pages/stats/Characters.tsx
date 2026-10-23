import { api } from '../../api/client'
import DetailsPage from '../../components/stats/DetailsPage'
import { DRILL_BTN, ROW, useDrill, useFlowMode, useLoad } from '../../components/stats/detailsUtil'
import { pct } from '../../lib/score'

export default function Characters() {
  const flow = useFlowMode(), drill = useDrill()
  const { data, err } = useLoad(() => api.stats.characters(flow ? 'flow' : undefined), [flow])
  return (
    <DetailsPage title="Characters" flowOnly={flow} err={err} loading={!data}
      note="Characters you've said at least 3 times in the last 30 days. Neutral-tone characters are left out: their tone isn't scored.">
      {data?.characters.length ? data.characters.map((c) => (
        <div key={c.ch} className={ROW}>
          <span className="font-hanzi text-xl text-fg">{c.ch}</span>
          <span className="text-sm text-fgdim">{c.pinyin}</span>
          <span className="text-fg">{pct(c.score)}</span>
          <span className="text-sm text-fgdim">{`tone ${c.tone_right == null ? '—' : pct(c.tone_right)} · sound ${c.sound_right == null ? '—' : pct(c.sound_right)}`}</span>
          <span className="text-sm text-fgdim">{`${c.takes} takes`}</span>
          {c.trend != null && <span className={c.trend >= 0 ? 'text-ok' : 'text-bad'}>{c.trend >= 0 ? '↑' : '↓'} {Math.abs(Math.round(c.trend * 100))}</span>}
          <button type="button" className={DRILL_BTN} aria-label={`Drill ${c.ch}`} onClick={() => drill('char', c.ch)}>Drill this</button>
        </div>)) : <p className="text-sm text-fgdim">No characters yet.</p>}
    </DetailsPage>
  )
}
