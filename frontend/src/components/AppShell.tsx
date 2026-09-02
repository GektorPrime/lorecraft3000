import { useEffect, useRef, useState, type MouseEvent, type ReactNode } from 'react'
import { CommandPalette } from './CommandPalette'
import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

interface AppShellProps {
  children: ReactNode
}

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

/** Responsive application shell. On narrow screens Sidebar becomes a modal
 * drawer: focus enters it, stays inside on Tab, and returns to the trigger on
 * every close path. Desktop layout is CSS-only and never enters modal mode. */
export function AppShell({ children }: AppShellProps) {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [paletteOpen, setPaletteOpen] = useState(false)
  const menuButtonRef = useRef<HTMLButtonElement>(null)
  const dismissRef = useRef<HTMLButtonElement>(null)
  const paletteReturnFocusRef = useRef<HTMLElement | null>(null)

  const closeDrawer = () => setDrawerOpen(false)
  const openPalette = () => {
    const focused = document.activeElement
    paletteReturnFocusRef.current = focused instanceof HTMLElement ? focused : null
    setPaletteOpen(true)
  }
  const openPaletteFromButton = (event: MouseEvent<HTMLButtonElement>) => {
    paletteReturnFocusRef.current = event.currentTarget
    setPaletteOpen(true)
  }

  useEffect(() => {
    if (!drawerOpen) return

    const previousOverflow = document.body.style.overflow
    const menuButton = menuButtonRef.current
    document.body.style.overflow = 'hidden'
    dismissRef.current?.focus()

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        closeDrawer()
        return
      }
      if (event.key !== 'Tab') return

      const sidebar = document.getElementById('app-sidebar')
      const focusable = sidebar
        ? Array.from(sidebar.querySelectorAll<HTMLElement>(FOCUSABLE)).filter(
            (element) => !element.hasAttribute('disabled'),
          )
        : []
      if (focusable.length === 0) return

      const first = focusable[0]
      const last = focusable[focusable.length - 1]
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', handleKeyDown)
      menuButton?.focus()
    }
  }, [drawerOpen])

  return (
    <div className="app-shell">
      <Sidebar
        open={drawerOpen}
        onClose={closeDrawer}
        dismissRef={dismissRef}
        onCommandClick={openPaletteFromButton}
      />
      {drawerOpen && (
        <button
          type="button"
          className="app-scrim"
          aria-label="Close navigation"
          onClick={closeDrawer}
        />
      )}
      <div className="app-shell__body">
        <Topbar
          drawerOpen={drawerOpen}
          onMenuClick={() => setDrawerOpen(true)}
          menuButtonRef={menuButtonRef}
          onCommandClick={openPaletteFromButton}
        />
        {children}
      </div>
      <CommandPalette
        open={paletteOpen}
        onRequestOpen={openPalette}
        onRequestClose={() => setPaletteOpen(false)}
        returnFocusRef={paletteReturnFocusRef}
      />
    </div>
  )
}
