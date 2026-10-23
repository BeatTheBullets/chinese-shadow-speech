import { api } from '../../api/client'
import DetailsPage from '../../components/stats/DetailsPage'
import { useDrill, useFlowMode, useLoad } from '../../components/stats/detailsUtil'
import SoundsPanel from '../../components/SoundsPanel'

export default function Sounds() {
  const flow = useFlowMode(), drill = useDrill()
  const { data, err } = useLoad(() => api.stats.sounds(flow ? 'flow' : undefined), [flow])
  return (
    <DetailsPage title="Sounds" flowOnly={flow} err={err} loading={!data}>
      {data && <SoundsPanel stats={data} onDrill={(k) => drill('sound', k)} />}
      <p className="text-sm text-fgdim">Hard sounds are the ones the score uses.</p>
      <p className="text-sm text-fgdim">Not checked yet: j/q/x mix-ups and breathy vs plain consonants (b/p, d/t, g/k, j/q, zh/ch, z/c).</p>
    </DetailsPage>
  )
}
