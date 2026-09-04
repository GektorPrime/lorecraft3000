import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { getOptionsSummary } from './client'
import { OptionsContext } from './optionsContext'
import type { OptionsSummary } from './types'
import { AsyncMessage } from '../components/AsyncMessage'

/**
 * Loads /api/v1/options/summary once and makes it available to every page
 * via useOptions() (see useOptions.ts) — the single source of truth for
 * model/size/aspect-ratio/role choices and the fixed explanatory copy for
 * reference-image weight and ref-set / panel immutability (issue #15).
 */
export function OptionsProvider({ children }: { children: ReactNode }) {
  const [options, setOptions] = useState<OptionsSummary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const requestVersion = useRef(0)

  const loadOptions = useCallback(async () => {
    const version = ++requestVersion.current
    setError(null)
    try {
      const value = await getOptionsSummary()
      if (version === requestVersion.current) setOptions(value)
    } catch (err) {
      if (version === requestVersion.current) {
        setError(err instanceof Error ? err.message : String(err))
      }
    }
  }, [])

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    void loadOptions()
    return () => {
      requestVersion.current += 1
    }
  }, [loadOptions])

  // After a laptop sleep the in-flight fetch can hang until the timeout
  // above surfaces an error, or the Vite proxy's keep-alive to the backend
  // is stale. Recover automatically when the tab becomes visible again or
  // the browser goes online, without requiring a server restart.
  useEffect(() => {
    if (options) return
    const maybeReload = () => {
      if (document.visibilityState !== 'visible') return
      void loadOptions()
    }
    const onOnline = () => void loadOptions()
    const onFocus = () => void loadOptions()
    document.addEventListener('visibilitychange', maybeReload)
    window.addEventListener('online', onOnline)
    window.addEventListener('focus', onFocus)
    return () => {
      document.removeEventListener('visibilitychange', maybeReload)
      window.removeEventListener('online', onOnline)
      window.removeEventListener('focus', onFocus)
    }
  }, [loadOptions, options])

  if (error) {
    return (
      <div>
        <AsyncMessage kind="error">Failed to load app configuration: {error}</AsyncMessage>
        <button type="button" className="btn" onClick={() => void loadOptions()}>Retry</button>
      </div>
    )
  }
  if (!options) {
    return <AsyncMessage kind="loading" aria-busy="true">Loading app configuration…</AsyncMessage>
  }
  return <OptionsContext.Provider value={options}>{children}</OptionsContext.Provider>
}
