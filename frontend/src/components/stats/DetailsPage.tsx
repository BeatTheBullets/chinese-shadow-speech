import Shell from '../Shell'
import Card from '../../ui/Card'
import DetailsHeader from './DetailsHeader'

// Shared frame of every details page: Shell, header, then the content in a notched card.
export default function DetailsPage({ title, window, flowOnly, note, err, loading, children }: {
  title: string; window?: string; flowOnly?: boolean; note?: string; err: string | null; loading: boolean; children: React.ReactNode
}) {
  return (
    <Shell>
      <main className="max-w-4xl mx-auto p-6 space-y-4">
        <DetailsHeader title={title} window={window} flowOnly={flowOnly} />
        {note && <p className="text-sm text-fgdim">{note}</p>}
        <Card notched className="p-5">
          <section className="space-y-2">
            {err ? <p className="text-sm text-bad">Could not load stats: {err}</p> : loading ? <p className="text-sm text-fgdim">Loading…</p> : children}
          </section>
        </Card>
      </main>
    </Shell>
  )
}
