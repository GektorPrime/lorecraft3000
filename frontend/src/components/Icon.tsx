import { ICON_PATHS, type IconName } from './iconPaths'

export type { IconName } from './iconPaths'

/**
 * Renders one glyph from the registry in `iconPaths.tsx`.
 *
 * Accessibility contract: icons are decorative by default and marked
 * `aria-hidden`, because they nearly always sit beside a real text label.
 * Pass `label` only when the icon is the *sole* content of a control, which
 * promotes it to `role="img"` with an accessible name.
 */
interface IconProps {
  name: IconName
  /** Rendered box in px. Icons are drawn on a 24-unit grid and scale cleanly. */
  size?: number
  /** Supply only when the icon carries meaning on its own. */
  label?: string
  className?: string
  strokeWidth?: number
}

export function Icon({ name, size = 20, label, className, strokeWidth = 2 }: IconProps) {
  return (
    <svg
      className={className ? `icon ${className}` : 'icon'}
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      role={label ? 'img' : undefined}
      aria-label={label}
      aria-hidden={label ? undefined : true}
      // IE/Edge legacy: keeps SVGs out of the tab order.
      focusable="false"
    >
      {ICON_PATHS[name]}
    </svg>
  )
}
