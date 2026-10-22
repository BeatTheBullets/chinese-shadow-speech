// Lacquer palette: single source for Tailwind (tailwind.config.ts) and for canvas/SVG code that cannot use classes.
export const TOKENS = {
  bg: '#2b0510', panel: '#3d0a1b', card: '#4E001B', line: '#6b1a33',
  fg: '#f6ead8', fgdim: '#c7a9a0', accent: '#F5CB00', ref: '#d6e6ea', you: '#F5CB00',
  ok: '#2bae85', warn: '#f0a020', bad: '#ff5a3c', sound: '#cca4e3', record: '#e0301e',
} as const satisfies Record<string, string>

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
