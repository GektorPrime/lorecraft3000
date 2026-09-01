import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ImageWithFallback } from './ImageWithFallback'

describe('ImageWithFallback', () => {
  it('replaces a failed image with accessible fallback content', () => {
    const onError = vi.fn()
    render(
      <ImageWithFallback src="/broken.jpg" alt="Portrait" fallback="PR" onError={onError} />,
    )

    fireEvent.error(screen.getByRole('img', { name: 'Portrait' }))

    expect(screen.getByRole('img', { name: 'Portrait' })).toHaveTextContent('PR')
    expect(screen.queryByRole('img', { name: 'Portrait' })?.tagName).toBe('SPAN')
    expect(onError).toHaveBeenCalledOnce()
  })

  it('tries the image again when its URL changes', () => {
    const { rerender } = render(
      <ImageWithFallback src="/broken.jpg" alt="Portrait" fallback="PR" />,
    )
    fireEvent.error(screen.getByRole('img', { name: 'Portrait' }))

    rerender(<ImageWithFallback src="/replacement.jpg" alt="Portrait" fallback="PR" />)

    expect(screen.getByRole('img', { name: 'Portrait' })).toHaveAttribute(
      'src',
      '/replacement.jpg',
    )
  })
})
