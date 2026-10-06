export type GuidedStep = 'listen' | 'whisper' | 'record'
export const nextGuidedStep = (s: GuidedStep): GuidedStep | null => (s === 'listen' ? 'whisper' : s === 'whisper' ? 'record' : null)
export const guidedText = (s: GuidedStep) => ({
  listen: { showText: true, label: 'Listen once' }, whisper: { showText: true, label: 'Whisper along (text visible)' }, record: { showText: false, label: 'Now record, text hidden' },
}[s])
