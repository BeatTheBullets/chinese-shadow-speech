export interface NoteInfo { noteId: number; modelName: string; tags: string[]; fields: Record<string, { value: string; order: number }> }
export interface AddNote {
  deckName: string; modelName: string; fields: Record<string, string>; tags: string[]
  options?: { allowDuplicate: boolean; duplicateScope: 'deck' | 'collection' }
  audio?: { filename: string; data: string; fields: string[] }[]
}

export async function ankiRequest<T>(url: string, action: string, params: Record<string, unknown> = {}): Promise<T> {
  const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action, version: 6, params }) })
  const data = (await res.json()) as { result: T; error: string | null }
  if (data.error) throw new Error(data.error)
  return data.result
}

export const anki = (url: string) => ({
  requestPermission: () => ankiRequest<{ permission: 'granted' | 'denied' }>(url, 'requestPermission'),
  deckNames: () => ankiRequest<string[]>(url, 'deckNames'),
  modelNames: () => ankiRequest<string[]>(url, 'modelNames'),
  modelFieldNames: (modelName: string) => ankiRequest<string[]>(url, 'modelFieldNames', { modelName }),
  findNotes: (query: string) => ankiRequest<number[]>(url, 'findNotes', { query }),
  notesInfo: (notes: number[]) => ankiRequest<NoteInfo[]>(url, 'notesInfo', { notes }),
  retrieveMediaFile: (filename: string) => ankiRequest<string | false>(url, 'retrieveMediaFile', { filename }),
  addNote: (note: AddNote) => ankiRequest<number>(url, 'addNote', { note }),
})
