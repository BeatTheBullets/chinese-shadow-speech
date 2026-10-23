import { api } from '../../api/client'
import DetailsPage from '../../components/stats/DetailsPage'
import { DRILL_BTN, ROW, useDrill, useFlowMode, useLoad } from '../../components/stats/detailsUtil'
import ToneMatrix from '../../components/ToneMatrix'
import ToneTrend from '../../components/ToneTrend'
import { TONE_NAMES, pct } from '../../lib/score'

export default function Tones() {
  const flow = useFlowMode(), drill = useDrill()
  const { data, err } = useLoad(() => api.stats.tones(flow ? 'flow' : undefined), [flow])
  return (
    <DetailsPage title="Tones" flowOnly={flow} err={err} loading={!data}>
      {data && (data.tones.length || data.pairs.length) ? (<>
        <ToneTrend weeks={data.weeks} />
        {data.tones.map((t) => (
          <div key={t.tone} className={ROW}>
            <span>Tone {t.tone} ({TONE_NAMES[t.tone]})</span><span>mean {pct(t.mean)}</span><span className="text-fgdim">n {t.n}</span>
            {t.tone >= 1 && t.tone <= 4 && <button type="button" className={DRILL_BTN} aria-label={`Drill tone ${t.tone}`} onClick={() => drill('tone', String(t.tone))}>Drill this</button>}
          </div>))}
        <h3 className="text-sm text-fgdim">After tone × tone</h3>
        <ToneMatrix pairs={data.pairs} onDrill={(k) => drill('pair', k)} />
      </>) : <p className="text-sm text-fgdim">No scores yet — record a take to see tone stats.</p>}
    </DetailsPage>
  )
}
