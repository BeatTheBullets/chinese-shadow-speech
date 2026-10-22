import { useEffect, useRef, useState } from 'react'
import type { Segment } from '../api/types'
import Button from '../ui/Button'
import ExportList, { type ExportItem } from './ExportList'

// End of a session (Finish session, closing the Flow summary, the back link): this session's practised sentences that
// are not in Anki yet. Closing without sending loses nothing: they stay in Review → Practised, not in Anki.
export default function SessionExportDialog({ items, onSent, onClose }: { items: ExportItem[]; onSent: (seg: Segment) => void; onClose: () => void }) {
  // Focus moves into the dialog, so Enter or Space no longer reaches the button that opened it (Finish session).
  const box = useRef<HTMLDivElement>(null)
  // While a send is in flight the dialog stays open: closing it would let the next one offer the same sentences again.
  const [busy, setBusy] = useState(false)
  useEffect(() => { box.current?.focus() }, [])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape' && !busy) onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose, busy])
  return (
    <div className="fixed inset-0 z-50 bg-bg/80 flex items-center justify-center p-4">
      <div ref={box} tabIndex={-1} role="dialog" aria-modal="true" aria-labelledby="session-export-title" className="outline-none bg-panel border border-line rounded-xl p-5 w-[560px] max-w-full max-h-[80vh] overflow-y-auto space-y-3 text-fg">
        <h3 id="session-export-title" className="font-semibold">Send what you practised to Anki?</h3>
        <p className="text-sm text-fgdim">Each sentence becomes a listening card. Fillers start unticked. Whatever you don't send stays in Review → Practised, not in Anki.</p>
        <ExportList items={items} onSent={onSent} onBusy={setBusy} />
        <div className="flex justify-end"><Button label="Close" keyHint="Esc" onClick={onClose} disabled={busy} /></div>
      </div>
    </div>
  )
}
