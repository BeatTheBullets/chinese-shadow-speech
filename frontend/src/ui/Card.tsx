import type { ReactNode } from 'react'

// `notched` (octagonal window-frame corners) is for main cards only; the clip-path would cut any border or shadow.
export default function Card({ notched, className = '', children }: { notched?: boolean; className?: string; children: ReactNode }) {
  return <div className={`${notched ? 'notch bg-card' : ''} ${className}`.trim()}>{children}</div>
}
