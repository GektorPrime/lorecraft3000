import type { ReactNode } from 'react'

interface PageHeaderProps {
  title: string
  description?: ReactNode
  actions?: ReactNode
  media?: ReactNode
}

/** Standard title/description/action layout for route pages. */
export function PageHeader({ title, description, actions, media }: PageHeaderProps) {
  return (
    <div className="page-header">
      {media && <div className="page-header__media">{media}</div>}
      <div className="page-header__copy">
        <h1>{title}</h1>
        {description && <p className="page-header__description">{description}</p>}
      </div>
      {actions && <div className="page-header__actions">{actions}</div>}
    </div>
  )
}
