import type { MouseEventHandler, Ref } from 'react'
import { NavLink } from 'react-router-dom'
import { BudgetMeter } from './BudgetMeter'
import { Icon, type IconName } from './Icon'
import { ThemeToggle } from './ThemeToggle'

interface NavItem {
  to: string
  label: string
  icon: IconName
  /** Exact matching, so /scenes does not light up on /scenes/new. */
  end?: boolean
}

/**
 * Navigation grouped by workflow rather than alphabetically: you define a
 * Library (characters, styles, base stages), use it to stage Work (scenes), and the
 * accepted results collect in the Gallery. The previous flat bar ordered
 * these arbitrarily.
 */
const TOP_ITEM: NavItem = { to: '/', label: 'Dashboard', icon: 'dashboard', end: true }

const NAV_GROUPS: { id: string; label: string; items: NavItem[] }[] = [
  {
    id: 'nav-group-library',
    label: 'Library',
    items: [
      { to: '/characters', label: 'Characters', icon: 'characters' },
      { to: '/styles', label: 'Styles', icon: 'styles' },
      { to: '/base-stages', label: 'Base Stages', icon: 'baseStages' },
    ],
  },
  {
    id: 'nav-group-work',
    label: 'Work',
    items: [
      { to: '/scenes', label: 'Scenes', icon: 'scenes', end: true },
      { to: '/gallery', label: 'Gallery', icon: 'gallery' },
      { to: '/panels', label: 'Panels', icon: 'panels', end: true },
    ],
  },
]

interface SidebarProps {
  /** Drawer state; only reachable below the shell breakpoint. */
  open?: boolean
  onClose?: () => void
  /** Lets the shell move focus here when the drawer opens. */
  dismissRef?: Ref<HTMLButtonElement>
  onCommandClick?: MouseEventHandler<HTMLButtonElement>
}

/**
 * The app's single <header>, and therefore its banner landmark: it carries the
 * brand and the primary navigation, which is what a banner is for. The topbar
 * is deliberately *not* a <header>, so "exactly one <header>" stays true
 * (Home.test.tsx) and the brand text appears exactly once in the document.
 *
 * Below the shell breakpoint this becomes an off-canvas drawer; above it, a
 * sticky full-height column.
 */
export function Sidebar({ open = false, onClose, dismissRef, onCommandClick }: SidebarProps) {
  return (
    <header
      id="app-sidebar"
      className={open ? 'app-sidebar app-sidebar--open' : 'app-sidebar'}
    >
      <div className="app-sidebar__brand">
        <NavLink to="/" className="app-sidebar__title" onClick={onClose}>
          LoreCraft3000
        </NavLink>
        <button
          ref={dismissRef}
          type="button"
          className="icon-button icon-button--ghost app-sidebar__dismiss"
          aria-label="Close navigation"
          onClick={onClose}
        >
          <Icon name="close" size="lg" />
        </button>
      </div>

      <nav className="app-sidebar__nav" aria-label="Primary">
        {onCommandClick && (
          <button type="button" className="app-sidebar__command" onClick={onCommandClick}>
            <Icon name="search" size="sm" />
            <span>Search</span>
            <kbd className="kbd">Cmd K</kbd>
          </button>
        )}

        <ul className="app-sidebar__list">
          <li>
            <NavLink
              to={TOP_ITEM.to}
              end={TOP_ITEM.end}
              className="app-sidebar__link"
              onClick={onClose}
            >
              <Icon name={TOP_ITEM.icon} size="md" />
              {TOP_ITEM.label}
            </NavLink>
          </li>
        </ul>

        {NAV_GROUPS.map((group) => (
          <div key={group.id} className="app-sidebar__group">
            <span className="app-sidebar__group-label" id={group.id}>
              {group.label}
            </span>
            <ul className="app-sidebar__list" aria-labelledby={group.id}>
              {group.items.map((item) => (
                <li key={item.to}>
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className="app-sidebar__link"
                    onClick={onClose}
                  >
                    <Icon name={item.icon} size="md" />
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <div className="app-sidebar__footer">
        <BudgetMeter />
        <ThemeToggle />
      </div>
    </header>
  )
}
