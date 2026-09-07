import { useTheme } from '../theme/useTheme'
import type { ThemePreference } from '../theme/theme'
import { Icon, type IconName } from './Icon'

const OPTIONS: { value: ThemePreference; icon: IconName; label: string }[] = [
  { value: 'system', icon: 'monitor', label: 'Match system theme' },
  { value: 'light', icon: 'sun', label: 'Light theme' },
  { value: 'dark', icon: 'moon', label: 'Dark theme' },
]

/**
 * Three-way theme control. `system` is a real, selectable option rather than
 * an implicit default, so a user who has pinned a theme can hand control back
 * to the OS.
 *
 * Modelled as a group of toggle buttons with `aria-pressed` rather than a
 * radio group: these apply immediately and are not part of a form submission.
 */
export function ThemeToggle() {
  const { preference, setPreference } = useTheme()

  return (
    <div className="theme-toggle" role="group" aria-label="Colour theme">
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          className="theme-toggle__option"
          aria-pressed={preference === option.value}
          aria-label={option.label}
          title={option.label}
          onClick={() => setPreference(option.value)}
        >
          <Icon name={option.icon} size="sm" />
        </button>
      ))}
    </div>
  )
}
