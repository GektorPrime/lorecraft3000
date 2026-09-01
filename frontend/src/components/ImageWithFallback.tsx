import { useState, type ImgHTMLAttributes, type ReactNode } from 'react'

interface ImageWithFallbackProps
  extends Omit<ImgHTMLAttributes<HTMLImageElement>, 'alt' | 'src'> {
  src: string | null | undefined
  alt: string
  fallback?: ReactNode
}

export function ImageWithFallback({
  src,
  alt,
  fallback = 'Image unavailable',
  className,
  onError,
  ...props
}: ImageWithFallbackProps) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null)

  if (!src || failedSrc === src) {
    return (
      <span
        className={['image-fallback', className].filter(Boolean).join(' ')}
        style={props.style}
        role="img"
        aria-label={alt}
      >
        {fallback}
      </span>
    )
  }

  return (
    <img
      {...props}
      className={className}
      src={src}
      alt={alt}
      onError={(event) => {
        setFailedSrc(src)
        onError?.(event)
      }}
    />
  )
}
