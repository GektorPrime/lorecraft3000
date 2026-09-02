import type { ReactNode } from 'react'

interface SectionHeaderProps {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  level?: 2 | 3
  className?: string
}

/** Consistent heading/action alignment within a page. Unlike PageHeader this
 * owns an h2/h3 and standard section rhythm, never a route-level h1. */
export function SectionHeader({
  title,
  description,
  actions,
  level = 2,
  className,
}: SectionHeaderProps) {
  const Heading = level === 2 ? 'h2' : 'h3'
  return (
    <div className={className ? `section-header ${className}` : 'section-header'}>
      <div className="section-header__copy">
        <Heading>{title}</Heading>
        {description && <p className="section-header__description">{description}</p>}
      </div>
      {actions && <div className="section-header__actions">{actions}</div>}
    </div>
  )
}
