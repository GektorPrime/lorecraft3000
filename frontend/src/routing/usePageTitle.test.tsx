import { render } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { APP_TITLE, usePageTitle } from './usePageTitle'

function Page({ title }: { title?: string }) {
  usePageTitle(title)
  return null
}

describe('usePageTitle', () => {
  it('sets a consistently formatted page title and updates it', () => {
    document.title = 'Before'
    const view = render(<Page title="Characters" />)
    expect(document.title).toBe(`Characters | ${APP_TITLE}`)

    view.rerender(<Page title="New Character" />)
    expect(document.title).toBe(`New Character | ${APP_TITLE}`)
  })

  it('uses the app name when no page title is supplied and restores the prior title', () => {
    document.title = 'Before'
    const view = render(<Page />)
    expect(document.title).toBe(APP_TITLE)

    view.unmount()
    expect(document.title).toBe('Before')
  })
})
