import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import SoundsPanel from './SoundsPanel'

const stats = {
  sounds: [{ key: 'ch>c', label: 'ch said as c', slips: 2, chances: 10, rate: 0.2, hard: true }],
  weeks: [{ week: '2026-W40', key: 'ch>c', rate: 0.4, slips: 2, chances: 5 }, { week: '2026-W41', key: 'ch>c', rate: 0.2, slips: 1, chances: 5 }],
}

describe('<SoundsPanel>', () => {
  it('shows label, slips of chances and rate, and drills by key', () => {
    const onDrill = vi.fn()
    render(<SoundsPanel stats={stats} onDrill={onDrill} />)
    expect(screen.getByText('ch said as c')).toBeInTheDocument()
    expect(screen.getByText('hard')).toBeInTheDocument()
    expect(screen.getByText('2 of 10')).toBeInTheDocument()
    expect(screen.getByText('20%')).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /ch said as c.*per week/ })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Drill ch said as c' }))
    expect(onDrill).toHaveBeenCalledWith('ch>c')
  })

  it('has an empty state', () => {
    render(<SoundsPanel stats={{ sounds: [], weeks: [] }} onDrill={vi.fn()} />)
    expect(screen.getByText('No sound results yet.')).toBeInTheDocument()
  })
})
