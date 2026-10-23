import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'

export function useFlowMode() { return useSearchParams()[0].get('mode') === 'flow' }

export function useDrill() {
  const nav = useNavigate()
  return (kind: string, key: string) => nav(`/drill?kind=${kind}&key=${encodeURIComponent(key)}`)
}

export function useLoad<T>(load: () => Promise<T>, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => {
    let cancelled = false
    load().then((v) => { if (!cancelled) setData(v) }).catch((e: unknown) => { if (!cancelled) setErr(e instanceof Error ? e.message : String(e)) })
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return { data, err }
}

export const ROW = 'border-b border-line py-1 flex gap-4 items-center'
export const DRILL_BTN = 'text-xs text-accent ml-auto hover:underline'
