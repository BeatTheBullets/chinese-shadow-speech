import type { Ref } from 'react'
import type { Word } from '../api/types'
import { fontSizeClass, sentenceRuns } from '../lib/sentence'

export interface SentenceProps {
  text: string; words: Word[] | null | undefined; showPinyin: boolean; showHanzi: boolean; translation?: string | null; showTranslation?: boolean
  pRef?: Ref<HTMLParagraphElement>  // the karaoke overlay measures the characters through it
}

export default function Sentence({ text, words, showPinyin, showHanzi, translation, showTranslation, pRef }: SentenceProps) {
  return (
    <div className="text-center">
      {showHanzi ? (
        <p ref={pRef} lang="zh" className={`sentence ${fontSizeClass(text.length)} ${showPinyin ? '' : 'hide-pinyin'}`}>
          {sentenceRuns(text, words).map((r, i) => (r.pinyin ? <ruby key={i}>{r.text}<rt>{r.pinyin}</rt></ruby> : r.text))}
        </p>
      ) : (
        <p className="sentence placeholder text-fgdim text-[28px] select-none">· · ·</p>
      )}
      {showTranslation && translation && <p className="text-fgdim italic text-sm mt-1">{translation}</p>}
    </div>
  )
}
