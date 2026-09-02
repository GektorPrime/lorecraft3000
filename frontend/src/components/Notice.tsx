import type { ReactNode } from 'react'
import { Icon, type IconName } from './Icon'

type NoticeTone = 'info' | 'warning' | 'privacy'

const ICONS: Record<NoticeTone, IconName> = {
  info: 'info',
  warning: 'alert',
  privacy: 'info',
}

interface NoticeProps {
  tone?: NoticeTone
  children: ReactNode
  className?: string
}

/** Persistent explanatory content. Unlike AsyncMessage this is deliberately
 * not a live region: it does not announce itself as an async status change. */
export function Notice({ tone = 'info', children, className }: NoticeProps) {
  const classes = ['notice', `notice--${tone}`, className].filter(Boolean).join(' ')
  return (
    <div className={classes}>
      <Icon name={ICONS[tone]} size={18} />
      <div className="notice__content">{children}</div>
    </div>
  )
}
