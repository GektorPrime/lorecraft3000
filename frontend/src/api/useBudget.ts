import { useContext } from 'react'
import { BudgetContext } from './budgetContext'

export function useBudget() {
  const value = useContext(BudgetContext)
  if (!value) throw new Error('useBudget must be used inside BudgetProvider')
  return value
}
