import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
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
  const requestVersion = useRef(0)

  const refreshBudget = useCallback(async () => {
    const version = ++requestVersion.current
    try {
      const nextBudget = await getBudget()
      if (version !== requestVersion.current) return
      setBudget(nextBudget)
      setRefreshError(null)
    } catch (err) {
      if (version !== requestVersion.current) return
      setRefreshError(err instanceof Error ? err.message : String(err))
    }
  }, [])

  useEffect(() => {
    const handleFocus = () => void refreshBudget()
    window.addEventListener('focus', handleFocus)
    return () => {
      requestVersion.current += 1
      window.removeEventListener('focus', handleFocus)
    }
  }, [refreshBudget])

  return (
    <BudgetContext.Provider value={{ budget, refreshBudget, refreshError }}>
      {children}
    </BudgetContext.Provider>
  )
}
