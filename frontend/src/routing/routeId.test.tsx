import { render, screen } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import { RouteIdGuard, parseRouteId } from './routeId'

describe('parseRouteId', () => {
  it.each([
    ['1', 1],
    ['42', 42],
    [String(Number.MAX_SAFE_INTEGER), Number.MAX_SAFE_INTEGER],
  ])('parses %s', (value, expected) => {
    expect(parseRouteId(value)).toBe(expected)
  })

  it.each([undefined, '', '0', '-1', '+1', '1.0', ' 1', '1 ', '01', 'abc', '9007199254740992'])(
    'rejects %s',
    (value) => {
      expect(parseRouteId(value)).toBeNull()
    },
  )
})

describe('RouteIdGuard', () => {
  it('passes a valid parsed ID to the page', () => {
    const router = createMemoryRouter(
      [{ path: '/things/:thingId', element: <RouteIdGuard paramName="thingId">{(id) => <p>Thing {id}</p>}</RouteIdGuard> }],
      { initialEntries: ['/things/27'] },
    )
    render(<RouterProvider router={router} />)

    expect(screen.getByText('Thing 27')).toBeInTheDocument()
  })

  it('renders the not-found page for an invalid ID', () => {
    const router = createMemoryRouter(
      [{ path: '/things/:id', element: <RouteIdGuard>{(id) => <p>Thing {id}</p>}</RouteIdGuard> }],
      { initialEntries: ['/things/0'] },
    )
    render(<RouterProvider router={router} />)

    expect(screen.getByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })
})
