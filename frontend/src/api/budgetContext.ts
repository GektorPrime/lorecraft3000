import { createContext } from 'react'
import type { Budget } from './types'

export interface BudgetContextValue {
  budget: Budget
  refreshBudget: () => Promise<void>
  refreshError: string | null
}

export const BudgetContext = createContext<BudgetContextValue | null>(null)
