import { useEffect, useState, type ReactNode } from 'react'
import { getOptionsSummary } from './client'
import { OptionsContext } from './optionsContext'
import type { OptionsSummary } from './types'

/**
 * Loads /api/v1/options/summary once and makes it available to every page
 * via useOptions() (see useOptions.ts) — the single source of truth for
 * model/size/aspect-ratio/role choices and the fixed explanatory copy for
 * reference-image weight and ref-set / panel immutability (issue #15).
 */
export function OptionsProvider({ children }: { children: ReactNode }) {
  const [options, setOptions] = useState<OptionsSummary | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getOptionsSummary()
      .then((value) => {
        if (!cancelled) setOptions(value)
      })
      .catch((err) => {
        if (!cancelled) setError(err instanceof Error ? err.message : String(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  if (error) {
    return <div className="banner banner--error">Failed to load app configuration: {error}</div>
  }
  if (!options) {
    return <p>Loading…</p>
  }
  return <OptionsContext.Provider value={options}>{children}</OptionsContext.Provider>
}
