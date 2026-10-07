import type { ExportNote } from '../store/settings'
import { anki, type NewModel } from './client'

// Listening cards (addendum §5.1): the sentence's audio on the front, what was said on the back.
export const LISTENING_DECK = 'shadow-speech'
export const LISTENING_MODEL = 'Shadow Listening'
export const LISTENING_FIELDS = ['Audio', 'Sentence', 'Pinyin', 'Translation', 'Source', 'Link']

export const listeningModel: NewModel = {
  modelName: LISTENING_MODEL,
  inOrderFields: LISTENING_FIELDS,
  isCloze: false,
  css: [
    '.card { font-family: "Noto Sans SC", "Inter", sans-serif; font-size: 20px; text-align: center; color: #1b1f24; background: #fafafa; }',
    '.prompt { color: #7c8793; margin-top: 1em; }',
    '.sentence { font-size: 34px; margin: .4em 0; }',
    '.pinyin { color: #4a86c8; }',
    '.translation { color: #555; font-style: italic; margin-top: .3em; }',
    '.source { font-size: 14px; color: #7c8793; margin-top: 1.2em; }',
    '.card.nightMode, .card.night_mode, .nightMode .card, .night_mode .card { color: #cfd6dd; background: #111418; }',
  ].join('\n'),
  cardTemplates: [{
    Name: 'Listening',
    Front: '{{Audio}}\n<div class="prompt">What did you hear?</div>',
    Back: [
      '{{FrontSide}}',
      '<hr id="answer">',
      '<div class="sentence">{{Sentence}}</div>',
      '<div class="pinyin">{{Pinyin}}</div>',
      '<div class="translation">{{Translation}}</div>',
      '<div class="source">{{#Link}}<a href="{{Link}}">{{Source}}</a>{{/Link}}{{^Link}}{{Source}}{{/Link}}</div>',
    ].join('\n'),
  }],
}

// The existing note type cannot be used (as opposed to an error AnkiConnect reported).
export class NoteTypeError extends Error {}

export interface ListeningSetup { deckCreated: boolean; modelCreated: boolean; exportNote: ExportNote }

// Creates the deck and the note type unless they exist (an existing one is used as it is, never changed) and returns
// the export settings that use them. AnkiConnect errors propagate with AnkiConnect's own message.
export async function setupListeningDeck(ankiUrl: string): Promise<ListeningSetup> {
  const a = anki(ankiUrl)
  const deckCreated = !(await a.deckNames()).includes(LISTENING_DECK)
  if (deckCreated) await a.createDeck(LISTENING_DECK)
  const modelCreated = !(await a.modelNames()).includes(LISTENING_MODEL)
  if (modelCreated) await a.createModel(listeningModel)
  const have = modelCreated ? LISTENING_FIELDS : await a.modelFieldNames(LISTENING_MODEL)
  if (!have.includes('Sentence') || !have.includes('Audio')) {
    throw new NoteTypeError(`The existing note type "${LISTENING_MODEL}" has no Sentence or Audio field. Rename it in Anki, then set up again.`)
  }
  const fields: ExportNote['fields'] = { sentence: 'Sentence', audio: 'Audio' }
  for (const [key, name] of [['pinyin', 'Pinyin'], ['translation', 'Translation'], ['source', 'Source'], ['link', 'Link']] as const) {
    if (have.includes(name)) fields[key] = name
  }
  return { deckCreated, modelCreated, exportNote: { deckName: LISTENING_DECK, modelName: LISTENING_MODEL, fields } }
}
