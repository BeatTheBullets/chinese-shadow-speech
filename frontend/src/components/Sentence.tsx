import type { Word } from '../api/types'
import { fontSizeClass, sentenceRuns } from '../lib/sentence'

interface Props { text: string; words: Word[] | null | undefined; showPinyin: boolean; showHanzi: boolean; translation?: string | null; showTranslation?: boolean }

export default function Sentence({ text, words, showPinyin, showHanzi, translation, showTranslation }: Props) {
  return (
    <div className="text-center">
      {showHanzi ? (
        <p lang="zh" className={`sentence ${fontSizeClass(text.length)} ${showPinyin ? '' : 'hide-pinyin'}`}>
          {sentenceRuns(text, words).map((r, i) => (r.pinyin ? <ruby key={i}>{r.text}<rt>{r.pinyin}</rt></ruby> : r.text))}
        </p>
      ) : (
        <p className="sentence placeholder text-fgdim text-[28px] select-none">· · ·</p>
      )}
      {showTranslation && translation && <p className="text-fgdim italic text-sm mt-1">{translation}</p>}
    </div>
  )
}
