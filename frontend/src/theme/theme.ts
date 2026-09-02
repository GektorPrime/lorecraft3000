/**
 * Theme preference primitives.
 *
 * Three preferences exist: `system` (follow the OS), `light` and `dark`.
 * `system` is expressed by *removing* the `data-theme` attribute, which lets
 * the `@media (prefers-color-scheme: dark)` block in `styles/tokens.css` take
 * over. Pinning a theme sets the attribute, and the token file's
 * `:root[data-theme='...']` selectors win over the media query.
 *
 * Every browser API touched here is optional: `localStorage` throws in some
 * privacy modes, and jsdom (used by the test suite) implements neither
 * `matchMedia` nor a real media-query engine. Each accessor degrades to the
 * light default instead of throwing.
 */

export type ThemePreference = 'system' | 'light' | 'dark'
export type ResolvedTheme = 'light' | 'dark'

export const THEME_STORAGE_KEY = 'lorecraft-theme'
export const DARK_QUERY = '(prefers-color-scheme: dark)'

const PREFERENCES: readonly ThemePreference[] = ['system', 'light', 'dark']

export function isThemePreference(value: unknown): value is ThemePreference {
  return typeof value === 'string' && (PREFERENCES as readonly string[]).includes(value)
}

export function readStoredPreference(): ThemePreference {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY)
    return isThemePreference(stored) ? stored : 'system'
  } catch {
    return 'system'
  }
}

export function persistPreference(preference: ThemePreference): void {
  try {
    if (preference === 'system') {
      window.localStorage.removeItem(THEME_STORAGE_KEY)
    } else {
      window.localStorage.setItem(THEME_STORAGE_KEY, preference)
    }
  } catch {
    // A non-persisted preference is still applied for this session.
  }
}

/** Reflects the preference onto <html>; `system` clears the attribute. */
export function applyPreferenceToDocument(preference: ThemePreference): void {
  const root = document.documentElement
  if (preference === 'system') {
    root.removeAttribute('data-theme')
  } else {
    root.setAttribute('data-theme', preference)
  }
}

function darkQuery(): MediaQueryList | null {
  return typeof window.matchMedia === 'function' ? window.matchMedia(DARK_QUERY) : null
}

export function prefersDark(): boolean {
  return darkQuery()?.matches ?? false
}

/** Subscribes to OS theme changes so `system` tracks them live. */
export function subscribeToSystemTheme(onChange: () => void): () => void {
  const query = darkQuery()
  if (!query?.addEventListener) return () => {}
  query.addEventListener('change', onChange)
  return () => query.removeEventListener('change', onChange)
}

export function resolveTheme(preference: ThemePreference, systemPrefersDark: boolean): ResolvedTheme {
  if (preference === 'system') return systemPrefersDark ? 'dark' : 'light'
  return preference
}
