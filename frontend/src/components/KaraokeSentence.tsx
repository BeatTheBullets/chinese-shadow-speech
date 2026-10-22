import { useLayoutEffect, useRef, useState } from 'react'
import { charRects, type Rect } from '../lib/charRects'
import { charFill, type Wipe } from '../lib/karaoke'
import Sentence, { type SentenceProps } from './Sentence'
import { TOKENS } from '../theme/tokens'

const FILL: Record<Wipe['tone'], string> = { ref: TOKENS.ref, ghost: `color-mix(in srgb, ${TOKENS.accent} 55%, transparent)` }

// The sentence with the karaoke wipe (addendum §6.5). The sentence DOM is Sentence's, unchanged (main spec §7.7); the
// wipe is a sibling layer — aria-hidden, pointer-events none — of boxes over each character's rectangle, multiplied
// into the light glyphs (and invisible on the dark background), so Yomitan still scans the real text underneath.
// The boxes are measured again when the sentence resizes, the window resizes and the web font has loaded.
export default function KaraokeSentence({ wipe, ...props }: SentenceProps & { wipe: Wipe | null }) {
  const pRef = useRef<HTMLParagraphElement>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const [rects, setRects] = useState<(Rect | null)[]>([])
  const { text, words, showHanzi, showPinyin } = props
  useLayoutEffect(() => {
    const p = pRef.current, box = boxRef.current
    if (!p || !box) { setRects([]); return }
    let live = true
    const measure = () => { if (live) setRects(charRects(p, box)) }
    measure()
    if ('fonts' in document) document.fonts.ready.then(measure, () => {})
    window.addEventListener('resize', measure)
    const ro = typeof ResizeObserver === 'undefined' ? null : new ResizeObserver(measure)
    ro?.observe(p)
    return () => { live = false; window.removeEventListener('resize', measure); ro?.disconnect() }
  }, [text, words, showHanzi, showPinyin])
  const fill = wipe ? charFill(text, wipe.progress) : []
  return (
    <div ref={boxRef} className="relative">
      <Sentence {...props} pRef={pRef} />
      {wipe && showHanzi && (
        <div aria-hidden="true" data-testid="wipe" className="absolute inset-0 pointer-events-none" style={{ mixBlendMode: 'multiply' }}>
          {rects.map((r, i) => (r && fill[i] > 0
            ? <div key={i} className="absolute" style={{ left: r.left, top: r.top, width: r.width * fill[i], height: r.height, background: FILL[wipe.tone] }} />
            : null))}
        </div>)}
    </div>
  )
}

// With the text hidden: one blank cell per speech character, filled at the wipe's pace (no text is revealed).
export function GhostLine({ count, wipe }: { count: number; wipe: Wipe | null }) {
  if (!count) return null
  return (
    <div aria-hidden="true" data-testid="ghost-line" className="flex justify-center flex-wrap gap-1 mt-2">
      {Array.from({ length: count }, (_, i) => {
        const f = wipe ? Math.max(0, Math.min(1, wipe.progress - i)) : 0
        return (
          <span key={i} className="w-4 h-4 rounded-sm bg-card overflow-hidden">
            <span className={`block h-full ${wipe?.tone === 'ghost' ? 'bg-you/60' : 'bg-ref'}`} style={{ width: `${f * 100}%` }} />
          </span>)
      })}
    </div>
  )
}
