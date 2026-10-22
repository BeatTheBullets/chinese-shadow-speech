import { useState } from 'react'
import { Link } from 'react-router-dom'
import { exportAndRecord, type LessonRef } from '../anki/export'
import type { Segment } from '../api/types'
import { initialSelection, isFiller } from '../lib/sessionExport'
import { useSettings } from '../store/settings'
import Button from '../ui/Button'
import { IconAnki } from '../ui/icons'

export interface ExportItem { segment: Segment; lesson: LessonRef }
type RowState = { status: 'sending' } | { status: 'sent' } | { status: 'failed'; error: string }

interface Props {
  items: ExportItem[]; onSent: (seg: Segment) => void
  onBusy?: (busy: boolean) => void // a send is in flight: the parent holds back anything that could send the same rows
  disabled?: boolean               // another send on the page is in flight
}

// Practised sentences to send to Anki as listening cards (addendum §5.2): all ticked except fillers; one click sends
// the ticked ones one after another; each row shows its own result. A failed row stays ticked for another try. A row
// whose sentence has a note by now (sent from elsewhere on the page) counts as sent.
export default function ExportList({ items, onSent, onBusy, disabled = false }: Props) {
  const { ankiUrl, exportNote } = useSettings()
  const [picked, setPicked] = useState(() => initialSelection(items.map((i) => i.segment)))
  const [rows, setRows] = useState<Record<number, RowState>>({})
  const [busy, setBusy] = useState(false)
  const sent = (s: Segment) => rows[s.id]?.status === 'sent' || s.anki_note_id != null
  const todo = items.filter((it) => picked.has(it.segment.id) && !sent(it.segment))
  if (!exportNote) {
    return <p className="text-sm text-fgdim">Set up the Anki export in Settings first (<Link className="text-accent underline" to="/settings">Settings → Anki → Set up chinese-shadow-speech deck</Link>).</p>
  }
  const cfg = exportNote
  const toggle = (id: number) => setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n })
  const working = (b: boolean) => { setBusy(b); onBusy?.(b) }
  async function send() {
    if (busy || disabled) return
    working(true)
    for (const it of todo) {
      const id = it.segment.id
      setRows((r) => ({ ...r, [id]: { status: 'sending' } }))
      try {
        const seg = await exportAndRecord(it.segment, ankiUrl, cfg, it.lesson)
        setRows((r) => ({ ...r, [id]: { status: 'sent' } }))
        onSent(seg)
      } catch (e) {
        setRows((r) => ({ ...r, [id]: { status: 'failed', error: e instanceof Error ? e.message : String(e) } }))
      }
    }
    working(false)
  }
  return (
    <div className="space-y-2">
      <ul>{items.map(({ segment: s }) => {
        const row: RowState | undefined = sent(s) ? { status: 'sent' } : rows[s.id]
        return (
          <li key={s.id} className="text-sm border-b border-line py-1.5 last:border-b-0">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={picked.has(s.id)} disabled={busy || disabled || row?.status === 'sent'} onChange={() => toggle(s.id)} />
              <span lang="zh" className="font-hanzi text-base text-fg flex-1">{s.text}</span>
              {isFiller(s.text) && <span className="text-[10px] text-fgdim">filler</span>}
              {row && <span className={`text-xs ${row.status === 'failed' ? 'text-bad' : row.status === 'sent' ? 'text-ok' : 'text-fgdim'}`}>
                {row.status === 'sent' ? 'sent ✓' : row.status === 'sending' ? 'sending…' : row.error}</span>}
            </label>
          </li>)
      })}</ul>
      <Button icon={<IconAnki />} label={`Send ${todo.length} to Anki`} variant="primary" onClick={() => void send()} disabled={busy || disabled || !todo.length} />
    </div>
  )
}
