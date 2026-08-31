import { createContext } from 'react'
import type { OptionsSummary } from './types'

/**
 * The React context object itself lives in its own non-component module so
 * that OptionsProvider.tsx (component) and useOptions.ts (hook) can each stay
 * "only exports one thing" files — required for the
 * react(only-export-components) fast-refresh lint rule to pass cleanly.
 */
export const OptionsContext = createContext<OptionsSummary | null>(null)
