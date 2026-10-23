import { Link, useLocation } from 'react-router-dom'

export default function DetailsHeader({ title, window = 'Last 30 days', flowOnly }: { title: string; window?: string; flowOnly?: boolean }) {
  const { pathname } = useLocation()
  return (
    <header className="space-y-1">
      <Link to="/stats" className="text-sm text-accent hover:underline">‹ Stats</Link>
      <h1 className="text-xl text-fg font-semibold">{title}</h1>
      <p className="text-sm text-fgdim flex items-center gap-3">
        <span>{window}</span>
        {flowOnly && <><span className="border border-line rounded px-2 text-xs text-fg">Flow only</span><Link to={pathname} className="text-accent hover:underline">All takes</Link></>}
      </p>
    </header>
  )
}
