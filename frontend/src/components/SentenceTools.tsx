import type { TextPrefs } from '../store/settings'
import { IconFlag } from '../ui/icons'

const TOGGLES: { k: keyof TextPrefs; face: string; name: string; key: string }[] = [
  { k: 'hanzi', face: '字', name: 'characters', key: 'T' },
  { k: 'pinyin', face: 'pīn', name: 'pinyin', key: 'P' },
  { k: 'translation', face: 'EN', name: 'English', key: 'E' },
]

// On the sentence card, next to what they act on (spec §2): ⚑ Difficult (F) and show/hide characters, pinyin and
// English (T/P/E). Chips, rounded not notched; pressed state in accent (warn for the flag); the key small under the face.
export default function SentenceTools({ flagged, onFlag, prefs, onToggle }: {
  flagged: boolean; onFlag: () => void; prefs: TextPrefs; onToggle: (k: keyof TextPrefs) => void
}) {
  const chip = (on: boolean, onTone: string) =>
    `flex flex-col items-center rounded-xl border px-2.5 py-1 text-xs ${on ? onTone : 'border-line text-fgdim'}`
  const hint = (key: string) => <span className="text-[9px] text-fgdim tracking-wider">{key}</span>
  return (
    <div className="flex items-start justify-center gap-1.5">
      <button type="button" aria-pressed={flagged} aria-label="Difficult (F)" onClick={onFlag} className={chip(flagged, 'border-warn text-warn')}>
        <span className="flex items-center gap-1"><span className="[&>svg]:w-3.5 [&>svg]:h-3.5"><IconFlag /></span>Difficult</span>{hint('F')}
      </button>
      <span aria-hidden="true" className="w-px self-stretch bg-line mx-1" />
      {TOGGLES.map(({ k, face, name, key }) => (
        <button key={k} type="button" aria-pressed={prefs[k]} aria-label={`${face} ${name} (${key})`} title={`Show or hide the ${name}`}
          onClick={() => onToggle(k)} className={chip(prefs[k], 'border-accent text-accent')}>
          <span className={k === 'hanzi' ? 'font-hanzi' : ''}>{face}</span>{hint(key)}
        </button>))}
    </div>
  )
}
