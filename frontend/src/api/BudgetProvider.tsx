import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { getBudget } from './client'
import { BudgetContext } from './budgetContext'
import { useOptions } from './useOptions'
import type { Budget } from './types'

export function BudgetProvider({ children }: { children: ReactNode }) {
  const options = useOptions()
  const [budget, setBudget] = useState<Budget>({
    daily_spend_cap_cents: options.daily_spend_cap_cents,
    spent_today_cents: options.spent_today_cents,
    remaining_today_cents: options.remaining_today_cents,
  })
  const [refreshError, setRefreshError] = useState<string | null>(null)

  const refreshBudget = useCallback(async () => {
    try {
      setBudget(await getBudget())
      setRefreshError(null)
    } catch (err) {
      setRefreshError(err instanceof Error ? err.message : String(err))
    }
  }, [])

  useEffect(() => {
    const handleFocus = () => void refreshBudget()
    window.addEventListener('focus', handleFocus)
    return () => window.removeEventListener('focus', handleFocus)
  }, [refreshBudget])

  return (
    <BudgetContext.Provider value={{ budget, refreshBudget, refreshError }}>
      {children}
    </BudgetContext.Provider>
  )
}
