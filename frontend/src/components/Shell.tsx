import { NavLink } from 'react-router-dom'

const TABS = [['/library', 'Library'], ['/review', 'Review'], ['/drill', 'Drill'], ['/stats', 'Stats'], ['/settings', 'Settings']]

// The top navigation (spec §6): on `panel`, plain words, the active tab underlined in accent. The same bar as Practice's TopBar.
export default function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-full">
      <header className="flex items-center justify-between px-6 bg-panel border-b border-line">
        <span className="py-3 text-sm text-fg tracking-wide">chinese-shadow-speech</span>
        <nav className="flex gap-5 text-sm">
          {TABS.map(([to, label]) => (
            <NavLink key={to} to={to} className={({ isActive }) => `py-3 border-b-2 ${isActive ? 'border-accent text-fg font-semibold' : 'border-transparent text-fgdim hover:text-fg'}`}>{label}</NavLink>))}
        </nav>
      </header>
      {children}
    </div>
  )
}
