import { useState } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Link, RouterProvider, createMemoryRouter, useNavigate } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useUnsavedChanges } from './useUnsavedChanges'

function TestForm() {
  const [value, setValue] = useState('')
  const navigate = useNavigate()
  const allowNavigation = useUnsavedChanges(value !== '')

  return (
    <>
      <label htmlFor="value">Value</label>
      <input id="value" value={value} onChange={(event) => setValue(event.target.value)} />
      <Link to="/other">Other page</Link>
      <button
        type="button"
        onClick={() => {
          allowNavigation()
          navigate('/other')
        }}
      >
        Save
      </button>
    </>
  )
}

function renderForm(initialEntries = ['/form'], initialIndex = initialEntries.length - 1) {
  const router = createMemoryRouter(
    [
      { path: '/form', element: <TestForm /> },
      { path: '/other', element: <h1>Other page</h1> },
      { path: '/previous', element: <h1>Previous page</h1> },
    ],
    { initialEntries, initialIndex },
  )
  render(<RouterProvider router={router} />)
  return router
}

describe('useUnsavedChanges', () => {
  afterEach(() => vi.restoreAllMocks())

  it('allows clean navigation without confirmation', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    const router = renderForm()

    await user.click(screen.getByRole('link', { name: 'Other page' }))

    expect(router.state.location.pathname).toBe('/other')
    expect(confirm).not.toHaveBeenCalled()
  })

  it('resets declined navigation and proceeds after confirmation', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    const user = userEvent.setup()
    const router = renderForm()
    const input = screen.getByLabelText('Value')

    await user.type(input, 'draft')
    const link = screen.getByRole('link', { name: 'Other page' })
    await user.click(link)

    expect(router.state.location.pathname).toBe('/form')
    expect(input).toHaveValue('draft')
    expect(link).toHaveFocus()

    await user.click(link)
    await waitFor(() => expect(router.state.location.pathname).toBe('/other'))
    expect(confirm).toHaveBeenCalledTimes(2)
  })

  it('blocks and resets POP navigation when changes are declined', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    const router = renderForm(['/previous', '/form'])

    await user.type(screen.getByLabelText('Value'), 'draft')
    await router.navigate(-1)

    await waitFor(() => expect(window.confirm).toHaveBeenCalled())
    expect(router.state.location.pathname).toBe('/form')
    expect(screen.getByLabelText('Value')).toHaveValue('draft')
  })

  it('requests a browser unload warning only while dirty', async () => {
    const user = userEvent.setup()
    renderForm()

    const cleanEvent = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(cleanEvent)
    expect(cleanEvent.defaultPrevented).toBe(false)

    await user.type(screen.getByLabelText('Value'), 'draft')
    const dirtyEvent = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(dirtyEvent)
    expect(dirtyEvent.defaultPrevented).toBe(true)

    await user.clear(screen.getByLabelText('Value'))
    const restoredEvent = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(restoredEvent)
    expect(restoredEvent.defaultPrevented).toBe(false)
  })

  it('bypasses both protections after a successful save', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    const router = renderForm()

    await user.type(screen.getByLabelText('Value'), 'draft')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    expect(router.state.location.pathname).toBe('/other')
    expect(confirm).not.toHaveBeenCalled()
  })
})
