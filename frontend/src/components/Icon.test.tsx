import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Icon } from './Icon'
import { ICON_NAMES } from './iconPaths'

describe('Icon', () => {
  it('is hidden from assistive technology by default', () => {
    const { container } = render(<Icon name="plus" />)
    const svg = container.querySelector('svg')

    expect(svg).toHaveAttribute('aria-hidden', 'true')
    expect(svg).not.toHaveAttribute('role')
  })

  it('becomes an image with an accessible name when labelled', () => {
    render(<Icon name="close" label="Close" />)

    const svg = screen.getByRole('img', { name: 'Close' })
    expect(svg).not.toHaveAttribute('aria-hidden')
  })

  it('inherits colour and keeps itself out of the tab order', () => {
    const { container } = render(<Icon name="check" />)
    const svg = container.querySelector('svg')

    expect(svg).toHaveAttribute('stroke', 'currentColor')
    expect(svg).toHaveAttribute('focusable', 'false')
  })

  it('applies the requested size to both axes', () => {
    const { container } = render(<Icon name="moon" size={32} />)
    const svg = container.querySelector('svg')

    expect(svg).toHaveAttribute('width', '32')
    expect(svg).toHaveAttribute('height', '32')
  })

  it('merges a custom class without dropping the base class', () => {
    const { container } = render(<Icon name="sun" className="tile__glyph" />)

    expect(container.querySelector('svg')).toHaveClass('icon', 'tile__glyph')
  })

  it('renders drawable geometry for every registered name', () => {
    // Guards against a typo'd registry entry shipping as a blank square.
    for (const name of ICON_NAMES) {
      const { container, unmount } = render(<Icon name={name} />)
      const svg = container.querySelector('svg')

      expect(svg, name).not.toBeNull()
      expect(svg?.querySelectorAll('path, circle, rect, line').length, name).toBeGreaterThan(0)
      unmount()
    }
  })

  it('contains no emoji or text nodes, which the Home tiles forbid', () => {
    for (const name of ICON_NAMES) {
      const { container, unmount } = render(<Icon name={name} />)
      expect(container.textContent, name).toBe('')
      unmount()
    }
  })
})
