export interface Rect { left: number; top: number; width: number; height: number }

// Per character (code point) of the sentence's visible text — ruby base text and plain text, never <rt> pinyin — its
// widest client rectangle relative to `container` (a range can also yield empty ones, e.g. at a line break), or null
// where the browser gives none. Same order as charFill().
export function charRects(p: HTMLElement, container: HTMLElement): (Rect | null)[] {
  const base = container.getBoundingClientRect()
  const out: (Rect | null)[] = []
  const walker = document.createTreeWalker(p, NodeFilter.SHOW_TEXT, {
    acceptNode: (n) => (n.parentElement?.closest('rt') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
  })
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    let off = 0
    for (const ch of node.textContent ?? '') {
      const range = document.createRange()
      range.setStart(node, off); range.setEnd(node, off + ch.length)
      const r = typeof range.getClientRects === 'function' ? widest(range.getClientRects()) : undefined
      out.push(r ? { left: r.left - base.left, top: r.top - base.top, width: r.width, height: r.height } : null)
      off += ch.length
    }
  }
  return out
}

function widest(rects: DOMRectList): DOMRect | undefined {
  let best: DOMRect | undefined
  for (let i = 0; i < rects.length; i++) if (!best || rects[i].width > best.width) best = rects[i]
  return best
}
