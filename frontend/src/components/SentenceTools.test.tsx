import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import SentenceTools from './SentenceTools'

describe('<SentenceTools>', () => {
  afterEach(cleanup)

  it('⚑ Difficult and the 字 · pīn · EN toggles, each with its key hint, pressed as the state says', () => {
    const onFlag = vi.fn(), onToggle = vi.fn()
    render(<SentenceTools flagged={false} onFlag={onFlag} prefs={{ hanzi: true, pinyin: false, translation: true }} onToggle={onToggle} />)
    const flag = screen.getByRole('button', { name: 'Difficult (F)' })
    expect(flag).toHaveAttribute('aria-pressed', 'false')
    expect(flag).toHaveTextContent('Difficult')
    expect(flag).toHaveTextContent('F')
    expect(screen.getByRole('button', { name: '字 characters (T)' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'pīn pinyin (P)' })).toHaveAttribute('aria-pressed', 'false')
    expect(screen.getByRole('button', { name: 'EN English (E)' })).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(flag)
    expect(onFlag).toHaveBeenCalledTimes(1)
    fireEvent.click(screen.getByRole('button', { name: 'pīn pinyin (P)' }))
    expect(onToggle).toHaveBeenLastCalledWith('pinyin')
    fireEvent.click(screen.getByRole('button', { name: '字 characters (T)' }))
    expect(onToggle).toHaveBeenLastCalledWith('hanzi')
    fireEvent.click(screen.getByRole('button', { name: 'EN English (E)' }))
    expect(onToggle).toHaveBeenLastCalledWith('translation')
  })

  it('a flagged sentence shows Difficult pressed', () => {
    render(<SentenceTools flagged onFlag={() => {}} prefs={{ hanzi: true, pinyin: true, translation: false }} onToggle={() => {}} />)
    expect(screen.getByRole('button', { name: 'Difficult (F)' })).toHaveAttribute('aria-pressed', 'true')
  })
})
