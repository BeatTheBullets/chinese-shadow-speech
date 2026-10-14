import { NavLink } from 'react-router-dom'
export default function Shell({ children }: { children: React.ReactNode }) {
  const tab = 'px-3 py-1 rounded border border-line text-sm'
  return (
    <div className="min-h-full">
      <header className="flex items-center justify-between px-6 py-3 border-b border-line">
        <span className="text-fghi">chinese-shadow-speech</span>
        <nav className="flex gap-2">
          {[['/library', 'Library'], ['/review', 'Review'], ['/drill', 'Drill'], ['/stats', 'Stats'], ['/settings', 'Settings']].map(([to, label]) => (
            <NavLink key={to} to={to} className={({ isActive }) => `${tab} ${isActive ? 'bg-[#1c2a3a] border-accent text-white' : 'text-fgdim'}`}>{label}</NavLink>))}
        </nav>
      </header>
      {children}
    </div>
  )
}
