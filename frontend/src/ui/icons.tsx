import type { ReactNode } from 'react'

// One stroke style for the whole set (2 px, round caps/joins, currentColor) so icons take the button's text colour.
// Filled shapes (play, record, stop) use currentColor fill. Decorative: the button's label names the action.
function Svg({ children, filled = false }: { children: ReactNode; filled?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" focusable="false"
      fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      {children}
    </svg>
  )
}

export const IconChevronLeft = () => <Svg><path d="M15 18l-6-6 6-6" /></Svg>
export const IconChevronRight = () => <Svg><path d="M9 6l6 6-6 6" /></Svg>
export const IconPlay = () => <Svg filled><path d="M8 5l11 7-11 7z" /></Svg>
export const IconRecord = () => <Svg filled><circle cx="12" cy="12" r="6" /></Svg>
export const IconStop = () => <Svg filled><rect x="6" y="6" width="12" height="12" rx="2" /></Svg>
export const IconMe = () => <Svg><circle cx="12" cy="8" r="3.5" /><path d="M5 20c1.5-4 4-5.5 7-5.5s5.5 1.5 7 5.5" /></Svg>
export const IconAnki = () => <Svg><rect x="4" y="5" width="16" height="14" rx="2" /><path d="M8 9h8M8 13h5" /></Svg>
export const IconSound = () => <Svg><path d="M11 5L6 9H3v6h3l5 4z" /><path d="M15.5 8.5a5 5 0 010 7M18.5 5.5a9 9 0 010 13" /></Svg>
export const IconFlag = () => <Svg><path d="M5 21V4M5 4h11l-2 4 2 4H5" /></Svg>
export const IconReplay = () => <Svg><path d="M4 12a8 8 0 108-8H8" /><path d="M10 1L7 4l3 3" /></Svg>
