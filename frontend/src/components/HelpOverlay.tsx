import { useEffect } from 'react'
import { KEY_HELP, MODES, modeHelp, modeName } from '../lib/modeHelp'

// The four modes and the key map (addendum §6.4). Esc or ? closes it. It listens on the window itself: the page's
// shortcut handler ignores keys inside a dialog (and is off while the help is open), and focus starts on its button.
// The closing key goes no further (stopped and default-prevented), whichever window listener was added first, so the
// page never takes it as its own `?` and opens the help again; a held key's auto-repeat is ignored for the same reason.
export default function HelpOverlay({ chorusPasses, onClose }: { chorusPasses: number; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return
      if (e.key !== 'Escape' && e.key !== '?') return
      e.preventDefault(); e.stopImmediatePropagation()
      if (!e.repeat) onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="help-title" className="bg-panel border border-line rounded p-6 w-[640px] max-h-[90vh] overflow-y-auto space-y-4"
        onClick={(e) => e.stopPropagation()}>
        <h2 id="help-title" className="text-fg text-lg">How to practise</h2>
        <dl className="space-y-2 text-sm">{MODES.map((m) => (
          <div key={m}><dt className="text-fg">{modeName(m)}</dt><dd className="text-fgdim">{modeHelp(m, chorusPasses)}</dd></div>))}</dl>
        <h3 className="text-fg">Keys</h3>
        <table className="text-sm"><tbody>{KEY_HELP.map(([k, what]) => (
          <tr key={k}><td className="pr-4 text-fg font-mono whitespace-pre">{k}</td><td className="text-fgdim">{what}</td></tr>))}</tbody></table>
        <div className="text-right"><button className="btn" onClick={onClose} autoFocus>Got it (Esc)</button></div>
      </div>
    </div>
  )
}
