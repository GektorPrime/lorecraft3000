import { useContext } from 'react'
import { OptionsContext } from './optionsContext'
import type { OptionsSummary } from './types'

/**
 * Reads the OptionsSummary loaded by <OptionsProvider> (see
 * OptionsProvider.tsx) — the single source of truth for model/size/aspect-
 * ratio/role choices and the fixed explanatory copy for reference-image
 * weight and ref-set / panel immutability (issue #15).
 */
export function useOptions(): OptionsSummary {
  const options = useContext(OptionsContext)
  if (!options) {
    throw new Error('useOptions() must be used inside <OptionsProvider>')
  }
  return options
}
