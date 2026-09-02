import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { THEME_STORAGE_KEY } from '../theme/theme'
import { ThemeToggle } from './ThemeToggle'

describe('ThemeToggle', () => {
  beforeEach(() => {
    window.localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
  })

  afterEach(async () => {
    // useTheme's shared store outlives a render; return it to the default for
    // other tests in this worker rather than only clearing storage.
    render(<ThemeToggle />)
    await userEvent.click(screen.getAllByRole('button', { name: 'Match system theme' })[0])
    window.localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
  })

  it('exposes all three immediate theme choices', () => {
    render(<ThemeToggle />)

    expect(screen.getByRole('button', { name: 'Match system theme' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(screen.getByRole('button', { name: 'Light theme' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
    expect(screen.getByRole('button', { name: 'Dark theme' })).toHaveAttribute(
      'aria-pressed',
      'false',
    )
  })

  it('pins the selected theme and reflects the active option', async () => {
    const user = userEvent.setup()
    render(<ThemeToggle />)

    await user.click(screen.getByRole('button', { name: 'Dark theme' }))

    expect(screen.getByRole('button', { name: 'Dark theme' })).toHaveAttribute(
      'aria-pressed',
      'true',
    )
    expect(document.documentElement).toHaveAttribute('data-theme', 'dark')
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
  })
})
