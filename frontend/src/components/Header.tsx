import { Sidebar } from './Sidebar'

/**
 * Compatibility name for callers that render the application banner in
 * isolation (notably BudgetProvider tests). The app shell itself renders
 * Sidebar directly; keeping this tiny wrapper avoids coupling provider tests
 * to the responsive shell while preserving Header's public component API.
 */
export function Header() {
  return <Sidebar />
}
