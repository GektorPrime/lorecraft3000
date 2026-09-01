import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { DateTime } from './DateTime'

describe('DateTime', () => {
  it('renders a readable semantic time with normalized metadata', () => {
    const { container } = render(<DateTime value="2026-08-31 15:00:00" />)
    const time = container.querySelector('time')

    expect(time).toHaveAttribute('datetime', '2026-08-31T15:00:00.000Z')
    expect(time).toHaveAttribute('title')
    expect(time).not.toHaveTextContent('2026-08-31 15:00:00')
  })

  it('renders a configurable fallback for invalid values', () => {
    const { container } = render(
      <DateTime value="invalid" fallback="Date unavailable" />,
    )

    expect(screen.getByText('Date unavailable')).toBeInTheDocument()
    expect(container.querySelector('time')).not.toBeInTheDocument()
  })
})
