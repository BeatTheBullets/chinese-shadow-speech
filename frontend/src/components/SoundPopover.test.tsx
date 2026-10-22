import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SoundPopover, { type SoundControls } from './SoundPopover'

const sound = (over: Partial<SoundControls> = {}, guide: number | null = null): SoundControls => ({
  rate: 1, onRate: vi.fn(),
  volume: { reference: 0.8, guide, onReference: vi.fn(), onGuide: vi.fn() },
  ...over,
})

describe('<SoundPopover>', () => {
  afterEach(cleanup)

  it('the Sound button opens speed, the 0.75× preset and the speaker volume; Esc closes it', () => {
    render(<SoundPopover sound={sound()} />)
    expect(screen.queryByLabelText('Playback speed')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Sound' }))
    expect(screen.getByLabelText('Playback speed')).toHaveValue('1')
    expect(screen.getByRole('button', { name: '0.75× (S)' })).toBeInTheDocument()
    expect(screen.getByLabelText('Speaker volume')).toHaveValue('80')
    expect(screen.queryByLabelText('Guide level')).toBeNull()
    fireEvent.keyDown(document, { key: 'Escape' })
    expect(screen.queryByLabelText('Playback speed')).toBeNull()
  })

  it('shows the guide level only when it applies', () => {
    render(<SoundPopover sound={sound({}, 0.5)} />)
    fireEvent.click(screen.getByRole('button', { name: 'Sound' }))
    expect(screen.getByLabelText('Guide level')).toHaveValue('50')
  })

  it('the speed slider runs 0.6–1.0 in 0.05 steps and the preset toggles 0.75 ↔ 1 like the S key', () => {
    const s = sound()
    const { rerender } = render(<SoundPopover sound={s} />)
    fireEvent.click(screen.getByRole('button', { name: 'Sound' }))
    const slider = screen.getByLabelText('Playback speed')
    expect(slider).toHaveAttribute('min', '0.6'); expect(slider).toHaveAttribute('max', '1'); expect(slider).toHaveAttribute('step', '0.05')
    fireEvent.change(slider, { target: { value: '0.85' } })
    expect(s.onRate).toHaveBeenLastCalledWith(0.85)
    fireEvent.click(screen.getByRole('button', { name: '0.75× (S)' }))
    expect(s.onRate).toHaveBeenLastCalledWith(0.75)
    rerender(<SoundPopover sound={{ ...s, rate: 0.75 }} />)
    expect(screen.getByRole('button', { name: '0.75× (S)' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByRole('button', { name: '0.75× (S)' }))
    expect(s.onRate).toHaveBeenLastCalledWith(1)
  })
})
