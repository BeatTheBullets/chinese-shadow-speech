import type { ReactNode } from 'react'

type Variant = 'default' | 'primary' | 'record' | 'ghost'
const VARIANT: Record<Variant, string> = {
  default: 'bg-card border-line text-fg',   // spec §1.1: card is the button surface
  primary: 'bg-accent border-accent text-bg',
  record: 'bg-record border-record text-fg',
  ghost: 'bg-transparent border-transparent text-fg',
}

// Hint colour per variant, each >= 4.5:1 on its background (checked in Button.test.tsx); fgdim only on the dark surfaces.
const HINT: Record<Variant, string> = { default: 'text-fgdim', ghost: 'text-fgdim', record: 'text-fg', primary: 'text-bg' }

const SIZE = {
  sm: 'flex-row gap-1.5 px-2 py-0.5 [&_svg]:w-4 [&_svg]:h-4',
  md: 'flex-col gap-[3px] min-w-[58px] px-2 py-[7px]',
  lg: 'flex-col gap-[3px] min-w-[76px] p-2.5',
} as const

// Icon, then label, then the shortcut key small and grey UNDER the label: the key is a hint, never the button face.
// size sm (a track caption's play button): one slim row instead, icon, label and hint side by side, the icon at 16 px.
// ariaExpanded: for a button that opens a pop-up (Sound), so screen readers hear whether it is open.
// pulse: the next expected action (Record before a take, › after one) breathes gently (.pulse-next, index.css),
// instead of a "Ready — Enter to start" line saying so.
export default function Button({ icon, label, keyHint, variant = 'default', size = 'md', onClick, disabled, ariaLabel, ariaExpanded, pulse = false }: {
  icon?: ReactNode; label: string; keyHint?: string; variant?: Variant; size?: 'sm' | 'md' | 'lg'
  onClick?: () => void; disabled?: boolean; ariaLabel?: string; ariaExpanded?: boolean; pulse?: boolean
}) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} aria-label={ariaLabel ?? (keyHint ? `${label} (${keyHint})` : label)} aria-expanded={ariaExpanded}
      className={`flex items-center rounded-xl border text-xs disabled:opacity-40 ${VARIANT[variant]} ${SIZE[size]}${pulse ? ' pulse-next' : ''}`}>
      {icon}
      <span>{label}</span>
      {keyHint && <span className={`text-[9px] ${HINT[variant]} tracking-wider`}>{keyHint}</span>}
    </button>
  )
}
