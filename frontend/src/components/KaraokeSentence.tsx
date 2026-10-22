import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { charRects, type Rect } from '../lib/charRects'
import { charFill, type Wipe } from '../lib/karaoke'
import { isPunct } from '../lib/text'
import Sentence, { type SentenceProps } from './Sentence'
import { WIPE_FILL } from '../theme/tokens'
import Card from '../ui/Card'

const FILL: Record<Wipe['tone'], string> = WIPE_FILL

// The sentence with the karaoke wipe (addendum §6.5). The sentence DOM is Sentence's, unchanged (main spec §7.7); the
// wipe is a sibling layer — aria-hidden, pointer-events none — of boxes over each character's rectangle, multiplied
// into the light glyphs (and invisible on the dark background), so Yomitan still scans the real text underneath.
// The boxes are measured again when the sentence resizes, the window resizes and the web font has loaded.
// With `tools` (Practice, Drill) it is the notched sentence card: the sentence, then `children` (the ghost line),
// then the tools (SentenceTools) that act on it, and the sentence large (the one big text on screen). Without (a Flow
// run's current line) just the sentence, at its normal size.
// onSyllableClick: clicking a character plays that syllable of the reference (the Echo review has no reference cells).
// The sentence stays one text run per word, so the click is placed by the measured character boxes, not by elements.
export default function KaraokeSentence({ wipe, tools, children, onSyllableClick, ...props }: SentenceProps & { wipe: Wipe | null; tools?: ReactNode; children?: ReactNode; onSyllableClick?: (i: number) => void }) {
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
  // The character under the pointer, as its syllable (speech characters before it); punctuation and the space around
  // the text play nothing, nor does a click that ends a text selection (looking a word up, copying).
  const onClick = (e: React.MouseEvent) => {
    const p = pRef.current, box = boxRef.current, sel = window.getSelection()
    if (!onSyllableClick || !p || !box || (sel && !sel.isCollapsed)) return
    const base = box.getBoundingClientRect(), x = e.clientX - base.left, y = e.clientY - base.top
    const hit = charRects(p, box).findIndex((r) => r != null && x >= r.left && x < r.left + r.width && y >= r.top && y < r.top + r.height)
    const chars = [...text]
    if (hit < 0 || isPunct(chars[hit])) return
    onSyllableClick(chars.slice(0, hit).filter((c) => !isPunct(c)).length)
  }
  const clickable = onSyllableClick != null && props.showHanzi
  const sentence = (
    <div ref={boxRef} className={`relative${clickable ? ' cursor-pointer' : ''}`} onClick={clickable ? onClick : undefined}
      title={clickable ? 'Click a character to hear it' : undefined}>
      <Sentence {...props} pRef={pRef} large={tools != null} />
      {wipe && showHanzi && (
        <div aria-hidden="true" data-testid="wipe" className="absolute inset-0 pointer-events-none" style={{ mixBlendMode: 'multiply' }}>
          {rects.map((r, i) => (r && fill[i] > 0
            ? <div key={i} className="absolute" style={{ left: r.left, top: r.top, width: r.width * fill[i], height: r.height, background: FILL[wipe.tone] }} />
            : null))}
        </div>)}
    </div>
  )
  if (tools == null) return <>{sentence}{children}</>
  return (
    <div data-testid="sentence-card">
      <Card notched className="px-6 pt-5 pb-3 space-y-3">{sentence}{children}{tools}</Card>
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
          <span key={i} className="w-4 h-4 rounded-sm bg-line overflow-hidden">
            <span className={`block h-full ${wipe?.tone === 'ghost' ? 'bg-you/60' : 'bg-ref'}`} style={{ width: `${f * 100}%` }} />
          </span>)
      })}
    </div>
  )
}
