import { Children } from 'react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import Card from '../../ui/Card'

export function Bar({ value }: { value: number }) {
  const w = Math.round(Math.max(0, Math.min(1, value)) * 100)
  return <span className="inline-block h-2 w-24 bg-line rounded-sm align-middle" aria-hidden="true"><span className="block h-2 bg-accent rounded-sm" style={{ width: `${w}%` }} /></span>
}

export default function Widget({ title, to, allLabel, empty, children }: { title: string; to: string; allLabel: string; empty: string; children?: ReactNode }) {
  const has = Children.toArray(children).length > 0
  return (
    <Card notched className="p-5">
      <section className="space-y-2">
        <h2 className="text-fg font-semibold">{title}</h2>
        {has ? children : <p className="text-sm text-fgdim">{empty}</p>}
        <Link to={to} className="block text-xs text-accent text-right hover:underline">{allLabel} ›</Link>
      </section>
    </Card>
  )
}
