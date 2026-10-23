import { useNavigate } from 'react-router-dom'
import { api } from '../../api/client'
import DetailsPage from '../../components/stats/DetailsPage'
import { useLoad } from '../../components/stats/detailsUtil'
import { pct } from '../../lib/score'

export default function Sentences() {
  const nav = useNavigate()
  const { data, err } = useLoad(() => api.stats.sentences(), [])
  return (
    <DetailsPage title="Sentences" err={err} loading={!data}>
      {data?.sentences.length ? data.sentences.map((s) => (
        <button key={s.segment_id} type="button" onClick={() => nav(`/practice/${s.lesson_id}?idx=${s.idx}`)}
          className="border-b border-line py-1 flex gap-4 items-center w-full text-left hover:bg-line/20">
          <span className="min-w-0 flex-1">
            <span className="block truncate text-fg">{s.text}</span>
            <span className="block truncate text-xs text-fgdim">{s.lesson_title}</span>
          </span>
          {s.regressed && <span className="border border-bad text-bad rounded px-2 text-xs">regressed</span>}
          <span className="text-sm text-fg">{`last ${pct(s.last)}`}</span>
          <span className="text-sm text-fgdim">{`best ${pct(s.best)}`}</span>
          <span className="text-sm text-fgdim">{`${s.attempts} takes`}</span>
        </button>)) : <p className="text-sm text-fgdim">No sentences yet.</p>}
    </DetailsPage>
  )
}
