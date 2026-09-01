import type { ReactNode } from 'react'
import {
  formatDateTime,
  formatFullDateTime,
  toIsoDateTime,
} from '../utils/dates'

interface DateTimeProps {
  value: string | Date
  fallback?: ReactNode
}

export function DateTime({ value, fallback = 'Unknown date' }: DateTimeProps) {
  const dateTime = toIsoDateTime(value)
  const text = formatDateTime(value)
  const title = formatFullDateTime(value)

  if (!dateTime || !text || !title) return <span>{fallback}</span>

  return (
    <time dateTime={dateTime} title={title}>
      {text}
    </time>
  )
}
