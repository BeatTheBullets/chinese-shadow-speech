import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Segment } from '../api/types'
import type { FlowResult } from '../lib/flow'
import FlowSummary from './FlowSummary'

const noop = () => {}
const props = { segments: [], results: [], skipped: 0, onReplayAll: noop, onRunAgain: noop, onEcho: noop, onFlagWeakest: noop, onExportWeakest: noop, onDone: noop, onPlayPair: noop }

describe('<FlowSummary>', () => {
  it('rounds the run time to whole seconds without ever showing 60 s', () => {
    render(<FlowSummary {...props} elapsedS={119.6} />)
    expect(screen.getByRole('heading')).toHaveTextContent('2 min 0 s')
  })

  it('each row offers Echo on that sentence and no Chorus', () => {
    const onEcho = vi.fn()
    const segments = [{ id: 11, text: '你好', last_score: null }, { id: 12, text: '再见', last_score: null }] as Segment[]
    const results: FlowResult[] = [{ segmentId: 12, idx: 1, attemptId: null, url: 'blob:x', duration: 1 }]
    render(<FlowSummary {...props} segments={segments} results={results} elapsedS={10} onEcho={onEcho} />)
    expect(screen.queryByRole('button', { name: 'Chorus' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Echo' }))
    expect(onEcho).toHaveBeenCalledWith(1)
  })
})
