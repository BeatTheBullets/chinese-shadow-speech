// Punctuation and spacing exactly as the backend's PUNCT (shadow/ingest/text.py): the backend aligns and romanises
// every other character, so spans and syllables line up with the characters this does not skip.
const PUNCT = new Set([...'，。！？；：、“”‘’（）《》〈〉【】…—·,.!?;:()"\'[]<>-~～ 　\n\t「」『』'])
export const isPunct = (ch: string): boolean => PUNCT.has(ch)
export const speechChars = (text: string): string[] => [...text].filter((c) => !isPunct(c))
