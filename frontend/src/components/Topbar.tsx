import type { MouseEventHandler, Ref } from 'react'
import { useLocation } from 'react-router-dom'
import { Icon } from './Icon'

interface TopbarProps {
  drawerOpen: boolean
  onMenuClick: () => void
  menuButtonRef: Ref<HTMLButtonElement>
  onCommandClick: MouseEventHandler<HTMLButtonElement>
}

function pageLabel(pathname: string): string {
  if (pathname === '/') return 'Dashboard'
  if (pathname === '/scenes/new') return 'Stage new scene'
  if (pathname.startsWith('/scenes/') && pathname.endsWith('/preview')) return 'Scene preview'
  if (pathname.startsWith('/scenes/') && pathname.endsWith('/edit')) return 'Edit scene'
  if (pathname === '/scenes') return 'Scenes'
  if (pathname === '/panels/new') return 'New comic page'
  if (pathname.startsWith('/panels/') && pathname.endsWith('/edit')) return 'Comic page composer'
  if (pathname === '/panels') return 'Comic pages'
  if (pathname === '/characters/new') return 'New character'
  if (pathname.startsWith('/characters/') && pathname.endsWith('/edit')) return 'Edit character'
  if (pathname.startsWith('/characters/')) return 'Character'
  if (pathname === '/characters') return 'Characters'
  if (pathname === '/styles/new') return 'New style'
  if (pathname.startsWith('/styles/') && pathname.endsWith('/edit')) return 'Edit style'
  if (pathname === '/styles') return 'Styles'
  if (pathname === '/gallery') return 'Gallery'
  return 'Workspace'
}

/** Mobile-only chrome. It is intentionally not a <header>: Sidebar owns the
 * document's single banner landmark and the one visible brand occurrence. */
export function Topbar({
  drawerOpen,
  onMenuClick,
  menuButtonRef,
  onCommandClick,
}: TopbarProps) {
  const { pathname } = useLocation()

  return (
    <div className="app-topbar">
      <button
        ref={menuButtonRef}
        type="button"
        className="icon-button app-topbar__toggle"
        aria-label="Open navigation"
        aria-controls="app-sidebar"
        aria-expanded={drawerOpen}
        onClick={onMenuClick}
      >
        <Icon name="menu" size="lg" />
      </button>
      <span className="app-topbar__title">{pageLabel(pathname)}</span>
      <button
        type="button"
        className="app-topbar__command"
        aria-label="Open command palette"
        onClick={onCommandClick}
      >
        <Icon name="search" size="sm" />
        <kbd className="kbd">Cmd K</kbd>
      </button>
    </div>
  )
}
