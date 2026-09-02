import {
  useDeferredValue,
  useEffect,
  useRef,
  useState,
  type RefObject,
} from 'react'
import { useNavigate } from 'react-router-dom'
import { listCharacters, listPanels, listStyles } from '../api/client'
import { useTheme } from '../theme/useTheme'
import { Icon, type IconName } from './Icon'

interface CommandPaletteProps {
  open: boolean
  onRequestOpen: () => void
  onRequestClose: () => void
  returnFocusRef: RefObject<HTMLElement | null>
}

interface Command {
  id: string
  label: string
  detail: string
  category: string
  icon: IconName
  search: string
  to?: string
  action?: () => void
}

const RESULTS_ID = 'command-palette-results'
const MAX_RESULTS = 12

function searchable(...parts: (string | number)[]): string {
  return parts.join(' ').toLocaleLowerCase()
}

/**
 * Global navigation and action palette. Static commands are available
 * immediately; library records are fetched once on first open and cached for
 * the component's lifetime. Each collection settles independently so one
 * failed endpoint does not hide the other two.
 */
export function CommandPalette({
  open,
  onRequestOpen,
  onRequestClose,
  returnFocusRef,
}: CommandPaletteProps) {
  const navigate = useNavigate()
  const { setPreference } = useTheme()
  const dialogRef = useRef<HTMLDialogElement>(null)
  const inputRef = useRef<HTMLInputElement>(null)
  const loadStarted = useRef(false)
  const mounted = useRef(true)
  const [query, setQuery] = useState('')
  const deferredQuery = useDeferredValue(query)
  const [activeIndex, setActiveIndex] = useState(0)
  const [libraryCommands, setLibraryCommands] = useState<Command[]>([])
  const [loading, setLoading] = useState(false)
  const [loadWarning, setLoadWarning] = useState<string | null>(null)

  const close = () => onRequestClose()
  const staticCommands: Command[] = [
    {
      id: 'new-panel',
      label: 'Stage new panel',
      detail: 'Create a panel from your cast and visual style',
      category: 'Create',
      icon: 'sparkles',
      search: searchable('stage new panel create generate'),
      to: '/panels/new',
    },
    {
      id: 'new-character',
      label: 'New character',
      detail: 'Add a character to the library',
      category: 'Create',
      icon: 'characters',
      search: searchable('new character create library'),
      to: '/characters/new',
    },
    {
      id: 'new-style',
      label: 'New style',
      detail: 'Define a visual style contract',
      category: 'Create',
      icon: 'styles',
      search: searchable('new style create visual'),
      to: '/styles/new',
    },
    {
      id: 'theme-system',
      label: 'Theme: match system',
      detail: 'Follow your operating system appearance',
      category: 'Appearance',
      icon: 'monitor',
      search: searchable('theme system appearance colour color'),
      action: () => {
        setPreference('system')
        close()
      },
    },
    {
      id: 'theme-light',
      label: 'Theme: light',
      detail: 'Use the light colour theme',
      category: 'Appearance',
      icon: 'sun',
      search: searchable('theme light appearance colour color'),
      action: () => {
        setPreference('light')
        close()
      },
    },
    {
      id: 'theme-dark',
      label: 'Theme: dark',
      detail: 'Use the dark colour theme',
      category: 'Appearance',
      icon: 'moon',
      search: searchable('theme dark appearance colour color'),
      action: () => {
        setPreference('dark')
        close()
      },
    },
  ]

  const normalizedQuery = deferredQuery.trim().toLocaleLowerCase()
  const allCommands = [...staticCommands, ...libraryCommands]
  const results = (
    normalizedQuery
      ? allCommands.filter((command) => command.search.includes(normalizedQuery))
      : staticCommands
  ).slice(0, MAX_RESULTS)
  const safeActiveIndex = Math.min(activeIndex, Math.max(0, results.length - 1))
  const activeCommand = results[safeActiveIndex]

  const runCommand = (command: Command) => {
    if (command.to) {
      navigate(command.to)
      close()
    } else {
      command.action?.()
    }
  }

  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  // Cmd/Ctrl+K works from every route, even when focus is inside a form.
  useEffect(() => {
    const handleShortcut = (event: KeyboardEvent) => {
      if (event.key.toLocaleLowerCase() !== 'k' || (!event.metaKey && !event.ctrlKey)) return
      event.preventDefault()
      if (open) {
        inputRef.current?.focus()
      } else {
        onRequestOpen()
      }
    }
    document.addEventListener('keydown', handleShortcut)
    return () => document.removeEventListener('keydown', handleShortcut)
  }, [open, onRequestOpen])

  // Keep native dialog state synchronized with React state.
  useEffect(() => {
    const dialog = dialogRef.current
    if (!dialog) return
    if (open && !dialog.open) {
      dialog.showModal()
      setQuery('')
      setActiveIndex(0)
      inputRef.current?.focus()
    } else if (!open && dialog.open) {
      dialog.close()
    }
  }, [open])

  // Fetch once. Promise.allSettled keeps partial search useful during a
  // backend issue instead of treating the three collections as all-or-none.
  useEffect(() => {
    if (!open || loadStarted.current) return
    loadStarted.current = true
    setLoading(true)
    void Promise.allSettled([listCharacters(), listStyles(), listPanels()]).then(
      ([charactersResult, stylesResult, panelsResult]) => {
        if (!mounted.current) return
        const commands: Command[] = []
        let failures = 0

        if (charactersResult.status === 'fulfilled') {
          commands.push(
            ...charactersResult.value.map((character) => ({
              id: `character-${character.id}`,
              label: character.name,
              detail: `Character - ${character.slug}`,
              category: 'Characters',
              icon: 'characters' as const,
              search: searchable(character.name, character.slug, 'character'),
              to: `/characters/${character.id}`,
            })),
          )
        } else failures += 1

        if (stylesResult.status === 'fulfilled') {
          commands.push(
            ...stylesResult.value.map((style) => ({
              id: `style-${style.id}`,
              label: style.name,
              detail: 'Visual style',
              category: 'Styles',
              icon: 'styles' as const,
              search: searchable(style.name, style.style_contract, 'style'),
              to: `/styles/${style.id}/edit`,
            })),
          )
        } else failures += 1

        if (panelsResult.status === 'fulfilled') {
          commands.push(
            ...panelsResult.value.map((panel) => ({
              id: `panel-${panel.id}`,
              label: `Panel #${panel.id}`,
              detail: panel.beat_text,
              category: 'Panels',
              icon: 'panels' as const,
              search: searchable(panel.id, panel.beat_text, 'panel'),
              to: `/panels/${panel.id}/preview`,
            })),
          )
        } else failures += 1

        setLibraryCommands(commands)
        setLoadWarning(
          failures === 0
            ? null
            : failures === 3
              ? 'Library search is temporarily unavailable.'
              : 'Some library results are temporarily unavailable.',
        )
        setLoading(false)
      },
    )

  }, [open])

  const runActive = () => {
    if (activeCommand) runCommand(activeCommand)
  }

  return (
    <dialog
      ref={dialogRef}
      className="command-palette"
      aria-label="Command palette"
      aria-modal="true"
      onCancel={(event) => {
        event.preventDefault()
        close()
      }}
      onKeyDown={(event) => {
        if (event.key === 'Escape') {
          event.preventDefault()
          close()
        }
      }}
      onClose={() => {
        onRequestClose()
        returnFocusRef.current?.focus()
      }}
      onClick={(event) => {
        if (event.target === event.currentTarget) close()
      }}
    >
      <div className="command-palette__surface">
        <div className="command-palette__search">
          <Icon name="search" size={19} />
          <input
            ref={inputRef}
            type="text"
            value={query}
            role="combobox"
            aria-label="Search commands"
            aria-expanded="true"
            aria-controls={RESULTS_ID}
            aria-autocomplete="list"
            aria-activedescendant={activeCommand ? `command-${activeCommand.id}` : undefined}
            autoComplete="off"
            placeholder="Search characters, styles, panels and actions"
            onChange={(event) => {
              setQuery(event.target.value)
              setActiveIndex(0)
            }}
            onKeyDown={(event) => {
              if (event.key === 'ArrowDown') {
                event.preventDefault()
                setActiveIndex((current) =>
                  results.length === 0 ? 0 : (current + 1) % results.length,
                )
              } else if (event.key === 'ArrowUp') {
                event.preventDefault()
                setActiveIndex((current) =>
                  results.length === 0 ? 0 : (current - 1 + results.length) % results.length,
                )
              } else if (event.key === 'Enter') {
                event.preventDefault()
                runActive()
              }
            }}
          />
          <kbd>Esc</kbd>
        </div>

        <div id={RESULTS_ID} className="command-palette__results" role="listbox">
          {results.map((command, index) => (
            <button
              key={command.id}
              id={`command-${command.id}`}
              type="button"
              role="option"
              aria-selected={index === safeActiveIndex}
              className="command-palette__option"
              tabIndex={-1}
              onPointerMove={() => setActiveIndex(index)}
              onClick={() => runCommand(command)}
            >
              <span className="command-palette__option-icon">
                <Icon name={command.icon} size={18} />
              </span>
              <span className="command-palette__option-copy">
                <strong>{command.label}</strong>
                <span>{command.detail}</span>
              </span>
              <span className="command-palette__category">{command.category}</span>
            </button>
          ))}

          {normalizedQuery && results.length === 0 && !loading && (
            <p className="command-palette__empty">No matching commands.</p>
          )}
        </div>

        <div className="command-palette__footer">
          <span>{loading ? 'Loading library...' : loadWarning}</span>
          <span>Up/Down Navigate - Enter Open</span>
        </div>
      </div>
    </dialog>
  )
}
