import { useEffect, useRef } from 'react'
import { KEY_HELP, MODES, modeHelp, modeName } from '../lib/modeHelp'
import Button from '../ui/Button'

// The two modes (Echo, Flow) and the key map (addendum §6.4). Esc or ? closes it. It listens on the window itself: the page's
// shortcut handler ignores keys inside a dialog (and is off while the help is open), and focus starts on its button.
// The closing key goes no further (stopped and default-prevented), whichever window listener was added first, so the
// page never takes it as its own `?` and opens the help again; a held key's auto-repeat is ignored for the same reason.
export default function HelpOverlay({ onClose }: { onClose: () => void }) {
  const actions = useRef<HTMLDivElement>(null)   // the shared Button takes no autoFocus: focus it from its row
  useEffect(() => { actions.current?.querySelector('button')?.focus() }, [])
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
    <div className="fixed inset-0 z-50 bg-bg/80 flex items-center justify-center p-4" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-labelledby="help-title"
        className="bg-panel border border-line rounded-xl p-6 w-[640px] max-w-full max-h-[90vh] overflow-y-auto space-y-5 text-fg"
        onClick={(e) => e.stopPropagation()}>
        <h2 id="help-title" className="text-lg font-semibold">How to practise</h2>
        <dl className="space-y-3 text-sm">{MODES.map((m) => (
          <div key={m}><dt className="text-accent font-semibold">{modeName(m)}</dt><dd className="text-fgdim">{modeHelp(m)}</dd></div>))}</dl>
        <h3 className="text-[10px] uppercase tracking-widest text-fgdim">Keys</h3>
        <table className="text-sm"><tbody>{KEY_HELP.map(([k, what]) => (
          <tr key={k}>
            <td className="pr-4 py-1 whitespace-nowrap">{k.split(/\s+/).map((cap) => (
              <kbd key={cap} className="mr-1 inline-block min-w-[26px] rounded-md border border-line bg-card px-1.5 py-0.5 text-center font-ui text-xs text-fg">{cap}</kbd>))}</td>
            <td className="text-fgdim">{what}</td>
          </tr>))}</tbody></table>
        <div ref={actions} className="flex justify-end"><Button label="Got it" keyHint="Esc" onClick={onClose} /></div>
      </div>
    </div>
  )
}
