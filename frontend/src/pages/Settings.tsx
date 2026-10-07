import { Fragment, useEffect, useRef, useState } from 'react'
import { LISTENING_DECK, LISTENING_MODEL, setupListeningDeck } from '../anki/listening'
import { anki } from '../anki/client'
import { bookmarkletCode } from '../lib/handoff'
import { useSettings } from '../store/settings'

export default function Settings() {
  const s = useSettings()
  const [status, setStatus] = useState<string>('')
  const [models, setModels] = useState<string[]>([])
  const [fields, setFields] = useState<string[]>([])
  const [exportFields, setExportFields] = useState<string[]>([])
  const [decks, setDecks] = useState<string[]>([])
  const [draft, setDraft] = useState({ name: '', query: '', model: '', sentence: '', audio: '', translation: '', source: '', url: '' })

  const bookmarklet = useRef<HTMLAnchorElement>(null)
  // Set outside JSX: React warns about javascript: URLs in href props.
  useEffect(() => { bookmarklet.current?.setAttribute('href', bookmarkletCode(window.location.origin)) }, [])

  async function connect() {
    try {
      const p = await anki(s.ankiUrl).requestPermission()
      if (p.permission !== 'granted') { setStatus('AnkiConnect denied access. Add this origin to webCorsOriginList in the add-on config.'); return }
      setModels(await anki(s.ankiUrl).modelNames()); setDecks(await anki(s.ankiUrl).deckNames()); setStatus('Connected')
    } catch (e) { setStatus(`Cannot reach AnkiConnect at ${s.ankiUrl}: ${(e as Error).message}`) }
  }
  // Addendum §5.1: create (or reuse, unchanged) the deck and note type for listening cards and export there.
  async function setupDeck() {
    if (!window.confirm(`Create the Anki deck "${LISTENING_DECK}" and the note type "${LISTENING_MODEL}" (unless they exist) and send exports there?`)) return
    try {
      const r = await setupListeningDeck(s.ankiUrl)
      s.set({ exportNote: r.exportNote })
      setStatus(`${r.deckCreated ? 'Created' : 'Using the existing'} deck ${LISTENING_DECK}, ${r.modelCreated ? 'created' : 'using the existing'} note type ${LISTENING_MODEL}. Exports now make listening cards there.`)
      const a = anki(s.ankiUrl)
      a.deckNames().then(setDecks).catch(() => {})
      a.modelNames().then(setModels).catch(() => {})
    } catch (e) {
      setStatus(`Could not set up the deck. AnkiConnect said: ${e instanceof Error ? e.message : String(e)}`)
    }
  }
  useEffect(() => { if (draft.model) anki(s.ankiUrl).modelFieldNames(draft.model).then(setFields).catch(() => setFields([])) }, [draft.model, s.ankiUrl])
  useEffect(() => { if (s.exportNote?.modelName) anki(s.ankiUrl).modelFieldNames(s.exportNote.modelName).then(setExportFields).catch(() => setExportFields([])) }, [s.exportNote?.modelName, s.ankiUrl])

  const sel = (label: string, value: string, onChange: (v: string) => void, opts: string[], allowEmpty = false) => (
    <label className="flex flex-col gap-1 text-sm text-fgdim">{label}
      <select className="bg-panel2 border border-line rounded px-2 py-1 text-fg" value={value} onChange={(e) => onChange(e.target.value)}>
        {allowEmpty && <option value="">—</option>}{opts.map((o) => <option key={o}>{o}</option>)}
      </select></label>)

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-8">
      <h1 className="text-xl text-fghi">Settings</h1>
      <section className="space-y-3">
        <h2 className="text-fghi">Anki</h2>
        <div className="flex gap-2 items-end">
          <label className="flex-1 text-sm text-fgdim">AnkiConnect URL
            <input className="w-full bg-panel2 border border-line rounded px-2 py-1 text-fg" value={s.ankiUrl} onChange={(e) => s.set({ ankiUrl: e.target.value })} /></label>
          <button className="btn" onClick={connect}>Connect</button>
        </div>
        <p className="text-sm text-fgdim">{status}</p>
        <div className="flex gap-2 items-center">
          <button className="btn" onClick={() => void setupDeck()}>Set up shadow-speech deck</button>
          <span className="text-xs text-fgdim">Listening cards: the sentence's audio on the front, sentence, pinyin, translation and a link to the video on the back.</span>
        </div>
        <h3 className="text-fg">Import queries</h3>
        <ul className="text-sm">{s.importQueries.map((q) => (
          <li key={q.name} className="flex justify-between border-b border-line py-1"><span>{q.name} · <code>{q.query}</code></span><button className="text-bad" onClick={() => s.removeQuery(q.name)}>remove</button></li>))}</ul>
        <div className="grid grid-cols-2 gap-3 bg-panel border border-line rounded p-3">
          <input className="inp" placeholder="Name (e.g. Mining)" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
          <input className="inp" placeholder="Query (e.g. deck:Mining tag:asbplayer)" value={draft.query} onChange={(e) => setDraft({ ...draft, query: e.target.value })} />
          {sel('Note type', draft.model, (v) => setDraft({ ...draft, model: v }), models, true)}
          {sel('Sentence field', draft.sentence, (v) => setDraft({ ...draft, sentence: v }), fields, true)}
          {sel('Audio field', draft.audio, (v) => setDraft({ ...draft, audio: v }), fields, true)}
          {sel('Translation field', draft.translation, (v) => setDraft({ ...draft, translation: v }), fields, true)}
          {sel('Source field', draft.source, (v) => setDraft({ ...draft, source: v }), fields, true)}
          {sel('URL field', draft.url, (v) => setDraft({ ...draft, url: v }), fields, true)}
          <button className="btn col-span-2" disabled={!draft.name || !draft.query || !draft.sentence || !draft.audio}
            onClick={() => { s.addQuery({ name: draft.name, query: draft.query, mapping: { sentence: draft.sentence, audio: draft.audio, translation: draft.translation || undefined, source: draft.source || undefined, url: draft.url || undefined } }); setDraft({ ...draft, name: '', query: '' }) }}>Add query</button>
        </div>
        <h3 className="text-fg">Export note type</h3>
        <div className="grid grid-cols-2 gap-3 bg-panel border border-line rounded p-3">
          {sel('Deck', s.exportNote?.deckName ?? '', (v) => { const cur = s.exportNote ?? { deckName: '', modelName: '', fields: { sentence: '', audio: '' } }; s.set({ exportNote: { deckName: v, modelName: cur.modelName, fields: cur.fields } }) }, decks, true)}
          {sel('Note type', s.exportNote?.modelName ?? '', (v) => { const cur = s.exportNote ?? { deckName: '', modelName: '', fields: { sentence: '', audio: '' } }; s.set({ exportNote: { deckName: cur.deckName, modelName: v, fields: cur.fields } }) }, models, true)}
          {(['sentence', 'pinyin', 'translation', 'audio', 'source', 'link'] as const).map((k) => { const cur = s.exportNote ?? { deckName: '', modelName: '', fields: { sentence: '', audio: '' } }; return (
            <Fragment key={k}>
              {sel(`${k} field`, cur.fields[k] ?? '', (v) => s.set({ exportNote: { deckName: cur.deckName, modelName: cur.modelName, fields: { ...cur.fields, [k]: v } } }), exportFields, true)}
            </Fragment>
          ) })}
        </div>
      </section>
      <section className="space-y-2">
        <h2 className="text-fghi">Practice</h2>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={s.practice.hideTextWhileRecording} onChange={(e) => s.set({ practice: { ...s.practice, hideTextWhileRecording: e.target.checked } })} /> Hide text while recording</label>
        {([['chorusPasses', 'Chorus passes'], ['flowGapFactor', 'Flow gap factor'], ['moveOnAfter', 'Move-on hint after N attempts'], ['defaultRate', 'Default speed']] as const).map(([k, label]) => {
          const clampFn = k === 'defaultRate' ? (v: number) => Math.max(0.6, Math.min(1.0, v)) : (v: number) => v
          return (
          <label key={k} className="flex items-center gap-2 text-sm">{label}
            <input type="number" step="0.05" className="inp w-24" value={s.practice[k]} onChange={(e) => { const val = e.target.value; if (val !== '') s.set({ practice: { ...s.practice, [k]: clampFn(Number(val)) } }) }} /></label>)
        })}
        <label className="flex items-center gap-2 text-sm">Language parent (speaker name)
          <input className="inp" value={s.languageParent ?? ''} onChange={(e) => s.set({ languageParent: e.target.value || null })} /></label>
      </section>
      <section className="space-y-2">
        <h2 className="text-fghi">YouTube</h2>
        <p className="text-sm text-fgdim">Drag this link to the Brave bookmarks bar. On a YouTube video, click it to send the video here.</p>
        <a ref={bookmarklet} className="btn inline-block" onClick={(e) => e.preventDefault()}>→ shadow-speech</a>
        <p className="text-sm text-fgdim">Videos behind an age or "not a bot" check need your YouTube cookies: export them to a
          cookies.txt file and set <code>[youtube] cookies_file</code> in config.toml (see docs/running.md, YouTube).</p>
      </section>
    </div>
  )
}
