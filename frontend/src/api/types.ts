export interface Syllable { ch: string; pinyin: string; pinyin_toneless: string; tone: number }  // tone: 0 neutral, 1-4, -1 non-hanzi
export interface Word { word: string; pinyin: string; tones: number[]; char_from: number; char_to: number; syllables: Syllable[] }
export interface AlignSpan { ch: string; start: number; end: number; conf: number }
export interface Segment {
  id: number; lesson_id: number; idx: number; start_s: number; end_s: number; text: string
  translation: string | null; words_json: Word[] | null; ref_alignment_json: AlignSpan[] | null
  difficulty_flag: boolean; anki_note_id: number | null
  last_score: number | null; best_score: number | null; attempts: number
}
export interface Lesson {
  id: number; title: string; speaker: string; source_type: 'upload' | 'youtube' | 'anki'; source_ref: string
  duration_s: number; created_at: string; status: 'queued' | 'processing' | 'ready' | 'error'; error: string | null
  segment_count: number; practised_count: number; mean_last_score: number | null; passage_count?: number; passages_done?: number
}
export interface Passage { idx: number; title: string; start_s: number; end_s: number; segment_ids: number[]; done: boolean }
export interface LessonDetail extends Lesson { segments: Segment[]; passages?: Passage[] }
// Phase 2 score JSON (spec §5.1). `overall` is null when the take was not scored; `warnings` then says why.
export type SylStatus = 'ok' | 'close' | 'wrong' | 'unvoiced' | 'missing'
export interface Contour { t0_s: number; step_ms: number; f0_st: (number | null)[]; spans: [number, number][] }
export interface ScoredSyllable {
  ch: string; pinyin: string; tone: number; target_tone: number | null; heard_tone: number | null; status: SylStatus
  tone_score: number | null; p_target: number | null; contour: number | null
}
export interface Score {
  overall: number | null; tone_overall: number | null; segmental_overall: number | null; rate_ratio: number | null
  ref_contour: Contour | null; usr_contour: Contour | null; syllables: ScoredSyllable[]; warnings: string[]
  heard_text?: string | null  // what the recogniser heard (null when the words check did not run)
  notices?: string[]          // a scored take's remarks, e.g. 'words_differ' (absent in older score JSON)
}
export interface Attempt { id: number; segment_id: number; session_id: number | null; created_at: string; mode: string; duration_s: number; score_json: Score | null }
// A sentence's newest stored attempt (GET /lessons/{id}/takes), and a past Flow run's takes in sentence order.
export interface Take { segment_id: number; attempt_id: number; mode: string; created_at: string; duration_s: number; score_json?: Score | null }
export interface FlowRun { started_at: string; ended_at: string; session_id: number | null; items: { segment_id: number; idx: number; attempt_id: number }[] }
export interface PracticeSession { id: number; lesson_id: number; mode: string; started_at: string; ended_at: string | null; attempts_count: number }
export interface Job { id: string; stage: string; fraction: number; status: 'queued' | 'running' | 'done' | 'error'; error: string | null; lesson_id: number | null }
export type Mode = 'echo' | 'chorus' | 'flow' | 'guided'
export interface AnkiNotePayload { note_id: number; text: string; translation?: string | null; source?: string | null; url?: string | null; audio_b64: string; filename: string }

export interface SentenceStat { segment_id: number; last: number; best: number; attempts: number }
export interface LessonStats {
  segments: { segment_id: number; idx: number; last: number | null; best: number | null; attempts: number; trend: number[] }[]
  sessions: { session_id: number; started_at: string; mean: number | null }[]
}
export interface ActivityStats { days: { date: string; minutes: number; attempts: number }[] }
export interface SentenceStats { regressed: SentenceStat[]; by_last: SentenceStat[] }
export interface SyllableStats { syllables: { ch: string; pinyin: string; tone: number; mean: number; n: number; trend: number | null }[] }
export interface ToneStats {
  tones: { tone: number; mean: number; n: number }[]
  pairs: { prev_tone: number; tone: number; mean: number; n: number }[]
  weeks: { week: string; tone: number; mean: number; n: number }[]
}
export interface VoiceProfile { baseline_hz: number | null; spread_st: number | null; voiced_s: number; updated_at: string | null }
export interface UnexportedItem {
  lesson_id: number; lesson_title: string; lesson_source_type: Lesson['source_type']; lesson_source_ref: string
  last_attempt_at: string; segment: Segment
}
