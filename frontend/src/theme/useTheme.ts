import { useCallback, useEffect, useSyncExternalStore } from 'react'
import {
  applyPreferenceToDocument,
  persistPreference,
  prefersDark,
  readStoredPreference,
  resolveTheme,
  subscribeToSystemTheme,
  type ResolvedTheme,
  type ThemePreference,
} from './theme'

/**
 * Module-level store rather than a React context: the theme has exactly one
 * value for the whole document, and a store keeps every consumer in sync
 * without threading another provider through the app shell. `useState` per
 * consumer would let two toggles drift apart.
 */
let preference: ThemePreference | null = null
const listeners = new Set<() => void>()

function getPreference(): ThemePreference {
  preference ??= readStoredPreference()
  return preference
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

function emit(): void {
  for (const listener of listeners) listener()
}

export interface UseThemeResult {
  /** What the user chose, including `system`. */
  preference: ThemePreference
  /** What that actually renders as right now. */
  resolved: ResolvedTheme
  setPreference: (next: ThemePreference) => void
}

export function useTheme(): UseThemeResult {
  const current = useSyncExternalStore(subscribe, getPreference)
  const systemPrefersDark = useSyncExternalStore(subscribeToSystemTheme, prefersDark)

  // Keeps <html data-theme> honest even when the pre-paint script in
  // index.html did not run (tests, or a stale document after HMR).
  useEffect(() => {
    applyPreferenceToDocument(current)
  }, [current])

  const setPreference = useCallback((next: ThemePreference) => {
    preference = next
    persistPreference(next)
    applyPreferenceToDocument(next)
    emit()
  }, [])

  return {
    preference: current,
    resolved: resolveTheme(current, systemPrefersDark),
    setPreference,
  }
}
