import { useState } from 'react'
import type { Segment } from '../api/types'

interface Props {
  segment: Segment; mode: 'edit' | 'split'; onSave: (text: string) => void; onSplit: (at: number) => void; onClose: () => void
  busy?: boolean; error?: string // busy: the change is being applied (re-alignment takes a moment)
}
// Edit a sentence's text, or pick where to split it. A modal dialog: the page shortcuts stay off while it is open.
export default function EditDialog({ segment, mode, onSave, onSplit, onClose, busy = false, error = '' }: Props) {
  const [text, setText] = useState(segment.text)
  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-center justify-center" onClick={() => { if (!busy) onClose() }}>
      <div role="dialog" aria-modal="true" aria-labelledby="edit-dialog-title" className="bg-panel border border-line rounded p-4 w-[520px] space-y-3"
        onClick={(e) => e.stopPropagation()} onKeyDown={(e) => { if (e.key === 'Escape' && !busy) onClose() }}>
        {mode === 'edit' ? (<>
          <h3 id="edit-dialog-title" className="text-fghi">Edit sentence</h3>
          <textarea className="inp w-full font-hanzi text-lg" rows={3} value={text} autoFocus disabled={busy} onChange={(e) => setText(e.target.value)} />
          <div className="flex justify-end gap-2">
            <button className="btn" onClick={onClose} disabled={busy}>Cancel</button>
            <button className="btn" onClick={() => onSave(text)} disabled={busy || !text.trim()}>{busy ? 'Re-aligning…' : 'Save and re-align'}</button>
          </div>
        </>) : (<>
          <h3 id="edit-dialog-title" className="text-fghi">{busy ? 'Splitting…' : 'Click the first character of the second half'}</h3>
          <p lang="zh" className="font-hanzi text-2xl leading-loose">{[...segment.text].map((ch, i) => (
            <button key={i} className="hover:bg-[#1c2a3a] rounded px-0.5 disabled:hover:bg-transparent" disabled={busy || i === 0} onClick={() => onSplit(i)}>{ch}</button>))}</p>
          <div className="flex justify-end"><button className="btn" onClick={onClose} disabled={busy} autoFocus>Cancel</button></div>
        </>)}
        {error && <p className="text-xs text-bad" role="alert">{error}</p>}
      </div>
    </div>
  )
}
