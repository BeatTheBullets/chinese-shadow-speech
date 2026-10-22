import type { ReactNode } from 'react'

type Variant = 'default' | 'primary' | 'record' | 'ghost'
const VARIANT: Record<Variant, string> = {
  default: 'bg-panel border-line text-fg',
  primary: 'bg-accent border-accent text-bg',
  record: 'bg-record border-record text-fg',
  ghost: 'bg-transparent border-transparent text-fg',
}

// Hint colour per variant, each >= 4.5:1 on its background (checked in Button.test.tsx); fgdim only on the dark surfaces.
const HINT: Record<Variant, string> = { default: 'text-fgdim', ghost: 'text-fgdim', record: 'text-fg', primary: 'text-bg' }

// Icon, then label, then the shortcut key small and grey UNDER the label: the key is a hint, never the button face.
export default function Button({ icon, label, keyHint, variant = 'default', size = 'md', onClick, disabled, ariaLabel }: {
  icon?: ReactNode; label: string; keyHint?: string; variant?: Variant; size?: 'md' | 'lg'
  onClick?: () => void; disabled?: boolean; ariaLabel?: string
}) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} aria-label={ariaLabel ?? (keyHint ? `${label} (${keyHint})` : label)}
      className={`flex flex-col items-center gap-[3px] rounded-xl border text-xs disabled:opacity-40 ${VARIANT[variant]} ${size === 'lg' ? 'min-w-[76px] p-2.5' : 'min-w-[58px] px-2 py-[7px]'}`}>
      {icon}
      <span>{label}</span>
      {keyHint && <span className={`text-[9px] ${HINT[variant]} tracking-wider`}>{keyHint}</span>}
    </button>
  )
}
