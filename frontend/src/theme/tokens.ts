// Lacquer palette: single source for Tailwind (tailwind.config.ts) and for canvas/SVG code that cannot use classes.
export const TOKENS = {
  bg: '#2b0510', panel: '#3d0a1b', card: '#4E001B', line: '#6b1a33',
  fg: '#f6ead8', fgdim: '#c7a9a0', accent: '#F5CB00', ref: '#d6e6ea', you: '#F5CB00',
  ok: '#2bae85', warn: '#f0a020', bad: '#ff5a3c', sound: '#cca4e3', record: '#cb2c1b',
} as const satisfies Record<string, string>

// The karaoke wipe's fills, multiplied into the light glyphs (KaraokeSentence). Not palette colours, so not in TOKENS or
// Tailwind. ref: a deeper moon blue-grey than the ref token, whose ~0.85 per channel barely moved fg (1.28:1); this one
// turns fg a visible blue-grey at >= 2:1 against the unwiped text (tokens.test.ts). ghost: the you colour itself, at
// full strength (it was 55%), so your pace guide turns the text you-gold.
export const WIPE_FILL = { ref: '#8fb3d9', ghost: TOKENS.you } as const

/** The colour a `fill` layer with mix-blend-mode multiply gives `base` (channel-wise product of #rrggbb colours). */
export function multiply(base: string, fill: string): string {
  return '#' + [1, 3, 5].map((i) => Math.round((parseInt(base.slice(i, i + 2), 16) * parseInt(fill.slice(i, i + 2), 16)) / 255)
    .toString(16).padStart(2, '0')).join('')
}

function lum(hex: string): number {
  const c = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4))
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
}
/** WCAG 2.x contrast ratio between two #rrggbb colours. */
export function contrast(a: string, b: string): number {
  const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x)
  return (hi + 0.05) / (lo + 0.05)
}
