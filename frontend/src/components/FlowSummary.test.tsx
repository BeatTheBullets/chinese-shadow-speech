import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import FlowSummary from './FlowSummary'

const noop = () => {}
const props = { segments: [], results: [], skipped: 0, onReplayAll: noop, onRunAgain: noop, onEcho: noop, onChorus: noop, onFlagWeakest: noop, onExportWeakest: noop, onDone: noop, onPlayPair: noop }

describe('<FlowSummary>', () => {
  it('rounds the run time to whole seconds without ever showing 60 s', () => {
    render(<FlowSummary {...props} elapsedS={119.6} />)
    expect(screen.getByRole('heading')).toHaveTextContent('2 min 0 s')
  })
})
