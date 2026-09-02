import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { THEME_STORAGE_KEY, type ThemePreference } from './theme'
import { useTheme } from './useTheme'

function Probe() {
  const { preference, resolved, setPreference } = useTheme()
  return (
    <div>
      <span data-testid="preference">{preference}</span>
      <span data-testid="resolved">{resolved}</span>
      {(['system', 'light', 'dark'] as ThemePreference[]).map((value) => (
        <button key={value} type="button" onClick={() => setPreference(value)}>
          {value}
        </button>
      ))}
    </div>
  )
}

/**
 * The hook keeps its preference in a module-level store so every consumer
 * shares one value. That store outlives a single test, so each test resets
 * storage and drives it back to `system` through the public API.
 */
async function resetToSystem() {
  window.localStorage.clear()
  render(<Probe />)
  await userEvent.click(screen.getAllByRole('button', { name: 'system' })[0])
}

describe('useTheme', () => {
  beforeEach(async () => {
    await resetToSystem()
  })

  afterEach(() => {
    window.localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
  })

  it('defaults to following the system and sets no data-theme attribute', () => {
    expect(screen.getAllByTestId('preference')[0]).toHaveTextContent('system')
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
  })

  it('resolves to light when the OS does not prefer dark', () => {
    expect(screen.getAllByTestId('resolved')[0]).toHaveTextContent('light')
  })

  it('pins dark on the document element and persists the choice', async () => {
    await userEvent.click(screen.getAllByRole('button', { name: 'dark' })[0])

    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    expect(screen.getAllByTestId('resolved')[0]).toHaveTextContent('dark')
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark')
  })

  it('clears the attribute and the stored value when returning to system', async () => {
    await userEvent.click(screen.getAllByRole('button', { name: 'light' })[0])
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')

    await userEvent.click(screen.getAllByRole('button', { name: 'system' })[0])

    // `system` must remove the attribute entirely so the prefers-color-scheme
    // media query in tokens.css regains control.
    expect(document.documentElement.hasAttribute('data-theme')).toBe(false)
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBeNull()
  })

  it('keeps separate consumers of the store in sync', async () => {
    render(<Probe />)
    const [first, second] = screen.getAllByTestId('preference')
    expect(second).toBeDefined()

    await act(async () => {
      await userEvent.click(screen.getAllByRole('button', { name: 'dark' })[0])
    })

    expect(first).toHaveTextContent('dark')
    expect(second).toHaveTextContent('dark')
  })
})
