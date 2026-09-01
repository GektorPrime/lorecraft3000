import type { HTMLAttributes } from 'react'

type AsyncMessageKind = 'loading' | 'success' | 'error'

interface AsyncMessageProps extends HTMLAttributes<HTMLParagraphElement> {
  kind: AsyncMessageKind
}

export function AsyncMessage({ kind, className, ...props }: AsyncMessageProps) {
  const isError = kind === 'error'

  return (
    <p
      {...props}
      className={[
        'banner',
        isError ? 'banner--error' : 'banner--info',
        className,
      ]
        .filter(Boolean)
        .join(' ')}
      role={isError ? 'alert' : 'status'}
      aria-live={isError ? undefined : 'polite'}
    />
  )
}
