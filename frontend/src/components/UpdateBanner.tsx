import { useEffect, useState } from 'react'
import { api } from '../api/client'

const KEY = 'update-dismissed'
const read = (): string | null => { try { return localStorage.getItem(KEY) } catch { return null } }
const write = (v: string) => { try { localStorage.setItem(KEY, v) } catch { /* private window: dismissed for this view only */ } }

export default function UpdateBanner() {
  const [info, setInfo] = useState<{ latest: string; url: string } | null>(null)
  const [dismissed, setDismissed] = useState(false)
  useEffect(() => {
    let live = true
    api.app.update().then((r) => {
      if (live && r.newer && r.latest && r.url && read() !== r.latest) setInfo({ latest: r.latest, url: r.url })
    }).catch(() => { /* no banner when the check fails */ })
    return () => { live = false }
  }, [])
  if (!info || dismissed) return null
  return (
    <div role="status" className="flex items-center gap-3 border border-line rounded-xl bg-panel px-4 py-2 text-sm">
      <span className="flex-1">A new version ({info.latest}) is available — <a className="underline" href={info.url} target="_blank" rel="noreferrer">Download</a></span>
      <button className="text-fgdim hover:text-fg" aria-label="Dismiss" onClick={() => { write(info.latest); setDismissed(true) }}>×</button>
    </div>
  )
}
