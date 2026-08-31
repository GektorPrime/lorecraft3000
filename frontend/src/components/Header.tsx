import { NavLink } from 'react-router-dom'
import { useOptions } from '../api/useOptions'

/**
 * The single app header, rendered once by the top-level layout in App.tsx
 * and shared by every route (including the homepage — issue #15 requires
 * the homepage to have exactly one <header>). Also surfaces the daily
 * spend budget everywhere, since it gates every generation.
 */
export function Header() {
  const options = useOptions()
  const spent = (options.spent_today_cents / 100).toFixed(2)
  const cap = (options.daily_spend_cap_cents / 100).toFixed(2)

  return (
    <header className="app-header">
      <div className="app-header__bar">
        <NavLink to="/" className="app-header__title">
          LoreCraft3000
        </NavLink>
        <nav className="app-header__nav" aria-label="Primary">
          <NavLink to="/characters">Characters</NavLink>
          <NavLink to="/styles">Styles</NavLink>
          <NavLink to="/panels">Panels</NavLink>
          <NavLink to="/panels/new">Stage new panel</NavLink>
        </nav>
        <span className="field__hint" title="Daily spend budget">
          Budget: ${spent} / ${cap}
        </span>
      </div>
    </header>
  )
}
