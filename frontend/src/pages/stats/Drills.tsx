import { api } from '../../api/client'
import DetailsPage from '../../components/stats/DetailsPage'
import { ROW, useLoad } from '../../components/stats/detailsUtil'
import { pct } from '../../lib/score'

export default function Drills() {
  const { data, err } = useLoad(() => api.drill.recent(10), [])
  return (
    <DetailsPage title="Drills" window="Last 10 drills" err={err} loading={!data}>
      {data?.length ? data.map((d) => (
        <div key={d.id} className={ROW}>
          <span data-drill-label>{d.label}</span><span className="text-fgdim">{d.started_at.slice(0, 10)}</span>
          {d.first_mean != null && d.best_mean != null && <span>{pct(d.first_mean)} → {pct(d.best_mean)}</span>}
        </div>)) : <p className="text-sm text-fgdim">No drills yet.</p>}
    </DetailsPage>
  )
}
