import { render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Notice } from './Notice'
import { PageHeader } from './PageHeader'
import { SectionHeader } from './SectionHeader'

describe('layout primitives', () => {
  it('keeps page media, copy and actions in one standard header anatomy', () => {
    render(
      <PageHeader
        media={<span data-testid="media">Portrait</span>}
        title="Elias"
        description="elias"
        actions={<button type="button">Edit</button>}
      />,
    )

    const heading = screen.getByRole('heading', { level: 1, name: 'Elias' })
    const header = heading.closest('.page-header')
    expect(header).not.toBeNull()
    expect(within(header as HTMLElement).getByTestId('media')).toBeInTheDocument()
    expect(within(header as HTMLElement).getByText('elias')).toHaveClass(
      'page-header__description',
    )
    expect(within(header as HTMLElement).getByRole('button', { name: 'Edit' })).toBeInTheDocument()
  })

  it('uses the same section heading/action anatomy at either valid level', () => {
    render(
      <SectionHeader
        level={3}
        title="Reference set v2"
        description="Draft"
        actions={<button type="button">Promote</button>}
      />,
    )

    const heading = screen.getByRole('heading', { level: 3, name: 'Reference set v2' })
    const header = heading.closest('.section-header')
    expect(header).not.toBeNull()
    expect(within(header as HTMLElement).getByText('Draft')).toHaveClass(
      'section-header__description',
    )
    expect(within(header as HTMLElement).getByRole('button', { name: 'Promote' })).toBeInTheDocument()
  })

  it('keeps persistent notices out of live-region roles', () => {
    render(<Notice tone="warning">Check these settings.</Notice>)

    expect(screen.getByText('Check these settings.').closest('.notice')).toHaveClass('notice--warning')
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })
})
