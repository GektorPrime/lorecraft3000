import { ICON_PATHS, type IconName } from './iconPaths'

export type { IconName } from './iconPaths'

/** The canonical icon scale. Values are the pixel bounds on the 24-unit grid. */
export type IconSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl'

const ICON_SIZE_PX: Record<IconSize, number> = {
  xs: 14,
  sm: 16,
  md: 18,
  lg: 20,
  xl: 22,
}

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
  /** A named scale entry, or a raw pixel size for one-off exceptions. */
  size?: IconSize | number
  /** Supply only when the icon carries meaning on its own. */
  label?: string
  className?: string
  strokeWidth?: number
}

export function Icon({
  name,
  size = 'lg',
  label,
  className,
  strokeWidth = 2,
}: IconProps) {
  const box = typeof size === 'number' ? size : ICON_SIZE_PX[size]
  return (
    <svg
      className={className ? `icon ${className}` : 'icon'}
      width={box}
      height={box}
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
