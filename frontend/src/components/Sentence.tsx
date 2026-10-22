import type { Ref } from 'react'
import type { Word } from '../api/types'
import { fontSizeClass, sentenceRuns } from '../lib/sentence'

export interface SentenceProps {
  text: string; words: Word[] | null | undefined; showPinyin: boolean; showHanzi: boolean; translation?: string | null; showTranslation?: boolean
  pRef?: Ref<HTMLParagraphElement>  // the karaoke overlay measures the characters through it
  large?: boolean                    // the sentence card's 1.5× size, pinyin scaled along (.sentence-lg)
}

export default function Sentence({ text, words, showPinyin, showHanzi, translation, showTranslation, pRef, large }: SentenceProps) {
  return (
    <div className="text-center">
      {showHanzi ? (
        <p ref={pRef} lang="zh" className={`sentence ${large ? 'sentence-lg ' : ''}${fontSizeClass(text.length, large)} ${showPinyin ? '' : 'hide-pinyin'}`}>
          {sentenceRuns(text, words).map((r, i) => (r.pinyin ? <ruby key={i}>{r.text}<rt>{r.pinyin}</rt></ruby> : r.text))}
        </p>
      ) : (
        <p className="sentence placeholder text-fgdim text-[28px] select-none">· · ·</p>
      )}
      {showTranslation && translation && <p className="text-fgdim italic text-sm mt-1">{translation}</p>}
    </div>
  )
}
