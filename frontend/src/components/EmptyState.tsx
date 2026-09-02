import type { ReactNode } from 'react'
import { Icon, type IconName } from './Icon'

interface EmptyStateProps {
  icon: IconName
  title: string
  description: string
  action?: ReactNode
  compact?: boolean
}

/** A deliberate empty state: what is missing, why it matters, and the next
 * useful action. Replaces bare "No items yet" paragraphs. */
export function EmptyState({ icon, title, description, action, compact = false }: EmptyStateProps) {
  return (
    <div className={compact ? 'empty-state empty-state--compact' : 'empty-state'}>
      <span className="empty-state__icon">
        <Icon name={icon} size={22} />
      </span>
      <div className="empty-state__copy">
        <h3>{title}</h3>
        <p>{description}</p>
      </div>
      {action && <div className="empty-state__action">{action}</div>}
    </div>
  )
}
