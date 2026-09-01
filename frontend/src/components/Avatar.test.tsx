import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Avatar } from './Avatar'

describe('Avatar', () => {
  it('renders an image when a url is provided', () => {
    render(<Avatar url="/api/v1/ref-images/7/content" initials="EL" name="Elias" />)
    const img = screen.getByRole('img', { name: 'Elias' })
    expect(img.tagName).toBe('IMG')
    expect(img).toHaveAttribute('src', '/api/v1/ref-images/7/content')
  })

  it('falls back to initials when there is no url', () => {
    render(<Avatar url={null} initials="EL" name="Elias" />)
    const fallback = screen.getByRole('img', { name: 'Elias' })
    expect(fallback.tagName).not.toBe('IMG')
    expect(fallback).toHaveTextContent('EL')
  })

  it('falls back after an image fails and retries when the url changes', () => {
    const { rerender } = render(
      <Avatar url="/broken.jpg" initials="EL" name="Elias" />,
    )
    fireEvent.error(screen.getByRole('img', { name: 'Elias' }))
    expect(screen.getByRole('img', { name: 'Elias' })).toHaveTextContent('EL')

    rerender(<Avatar url="/replacement.jpg" initials="EL" name="Elias" />)
    expect(screen.getByRole('img', { name: 'Elias' })).toHaveAttribute(
      'src',
      '/replacement.jpg',
    )
  })
})
