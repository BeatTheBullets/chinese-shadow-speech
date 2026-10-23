import { api } from '../../api/client'
import ActivityChart from '../../components/ActivityChart'
import DetailsPage from '../../components/stats/DetailsPage'
import { useLoad } from '../../components/stats/detailsUtil'

export default function Activity() {
  const { data, err } = useLoad(() => api.stats.activity(30), [])
  return (
    <DetailsPage title="Activity" window="Last 30 days" err={err} loading={!data}>
      {data && <ActivityChart days={data.days} />}
    </DetailsPage>
  )
}
