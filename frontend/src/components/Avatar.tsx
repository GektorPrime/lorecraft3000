interface AvatarProps {
  url: string | null
  initials: string
  name: string
  size?: number
}

/**
 * Renders a character's deterministically-selected canonical reference image
 * (see app/services/avatars.py) or, when there is none, a stable initials
 * fallback — used consistently across character list/detail and cast
 * selection (issue #15).
 */
export function Avatar({ url, initials, name, size = 40 }: AvatarProps) {
  const style = { width: size, height: size, fontSize: size * 0.4 }
  if (url) {
    return <img className="avatar" src={url} alt={name} style={style} />
  }
  return (
    <span className="avatar" style={style} aria-label={name} role="img">
      {initials}
    </span>
  )
}
