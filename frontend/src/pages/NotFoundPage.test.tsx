import { render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { NotFoundPage } from './NotFoundPage'

describe('NotFoundPage', () => {
  it('offers routes back to home and each collection', () => {
    const router = createMemoryRouter([{ path: '*', element: <NotFoundPage /> }], {
      initialEntries: ['/missing'],
    })
    render(<RouterProvider router={router} />)

    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(document.title).toBe('Page Not Found | LoreCraft3000')
    expect(screen.getByRole('link', { name: 'Home' })).toHaveAttribute('href', '/')
    expect(screen.getByRole('link', { name: 'character collection' })).toHaveAttribute(
      'href',
      '/characters',
    )
    expect(screen.getByRole('link', { name: 'style collection' })).toHaveAttribute(
      'href',
      '/styles',
    )
    expect(screen.getByRole('link', { name: 'scene collection' })).toHaveAttribute(
      'href',
      '/scenes',
    )
  })
})
