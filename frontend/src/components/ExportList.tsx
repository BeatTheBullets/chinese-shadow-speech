import { useState } from 'react'
import { Link } from 'react-router-dom'
import { exportAndRecord, type LessonRef } from '../anki/export'
import type { Segment } from '../api/types'
import { initialSelection, isFiller } from '../lib/sessionExport'
import { useSettings } from '../store/settings'

export interface ExportItem { segment: Segment; lesson: LessonRef }
type RowState = { status: 'sending' } | { status: 'sent' } | { status: 'failed'; error: string }

// Practised sentences to send to Anki as listening cards (addendum §5.2): all ticked except fillers; one click sends
// the ticked ones one after another; each row shows its own result. A failed row stays ticked for another try.
export default function ExportList({ items, onSent }: { items: ExportItem[]; onSent: (seg: Segment) => void }) {
  const { ankiUrl, exportNote } = useSettings()
  const [picked, setPicked] = useState(() => initialSelection(items.map((i) => i.segment)))
  const [rows, setRows] = useState<Record<number, RowState>>({})
  const [busy, setBusy] = useState(false)
  const todo = items.filter((it) => picked.has(it.segment.id) && rows[it.segment.id]?.status !== 'sent')
  if (!exportNote) {
    return <p className="text-sm text-fgdim">Set up the Anki export in Settings first (<Link className="underline" to="/settings">Settings → Anki → Set up shadow-speech deck</Link>).</p>
  }
  const cfg = exportNote
  const toggle = (id: number) => setPicked((p) => { const n = new Set(p); if (n.has(id)) n.delete(id); else n.add(id); return n })
  async function send() {
    if (busy) return
    setBusy(true)
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
    setBusy(false)
  }
  return (
    <div className="space-y-2">
      <ul className="space-y-1">{items.map(({ segment: s }) => {
        const row = rows[s.id]
        return (
          <li key={s.id} className="text-sm">
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={picked.has(s.id)} disabled={busy || row?.status === 'sent'} onChange={() => toggle(s.id)} />
              <span className="font-hanzi flex-1">{s.text}</span>
              {isFiller(s.text) && <span className="text-[10px] text-fgdim">filler</span>}
              {row && <span className={`text-xs ${row.status === 'failed' ? 'text-bad' : 'text-fgdim'}`}>
                {row.status === 'sent' ? 'sent ✓' : row.status === 'sending' ? 'sending…' : row.error}</span>}
            </label>
          </li>)
      })}</ul>
      <button className="btn" onClick={() => void send()} disabled={busy || !todo.length}>Send {todo.length} to Anki</button>
    </div>
  )
}
