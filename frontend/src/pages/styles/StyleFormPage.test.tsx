import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import { StyleFormPage } from './StyleFormPage'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    getStyle: vi.fn(),
    createStyle: vi.fn(),
    updateStyle: vi.fn(),
  }
})

const EXISTING_STYLE = {
  id: 5,
  name: 'Ink Wash',
  style_contract: 'Loose ink wash.',
  created_at: '',
}

describe('StyleFormPage', () => {
  function renderPage(path: string) {
    const router = createMemoryRouter(
      [
        { path: '/styles/new', element: <StyleFormPage /> },
        { path: '/styles/:id/edit', element: <StyleFormPage /> },
        { path: '/styles', element: <h1>Styles</h1> },
      ],
      { initialEntries: [path] },
    )
    render(<RouterProvider router={router} />)
    return router
  }

  beforeEach(() => {
    // mockReset (not just mockResolvedValue) so each test starts with a
    // clean call history — a previous test's successful submit must not
    // leak into a later test's "was this ever called" assertion.
    vi.mocked(client.getStyle).mockReset().mockResolvedValue(EXISTING_STYLE)
    vi.mocked(client.createStyle).mockReset().mockResolvedValue({ ...EXISTING_STYLE, id: 9 })
    vi.mocked(client.updateStyle).mockReset().mockResolvedValue(EXISTING_STYLE)
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('does not render a reference image control', async () => {
    renderPage('/styles/new')
    expect(screen.queryByLabelText('Reference image IDs')).not.toBeInTheDocument()
  })

  it('loads and updates a style without reference image IDs', async () => {
    const user = userEvent.setup()
    const router = renderPage('/styles/5/edit')
    const contract = await screen.findByLabelText('Style contract')
    await user.clear(contract)
    await user.type(contract, 'Updated wash.')
    await user.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(client.updateStyle).toHaveBeenCalled())
    expect(client.updateStyle).toHaveBeenCalledWith(5, {
      name: 'Ink Wash',
      style_contract: 'Updated wash.',
    })
    await waitFor(() => expect(router.state.location.pathname).toBe('/styles'))
  })

  it('rejects a malformed edit ID without loading a style', async () => {
    renderPage('/styles/bad/edit')

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(client.getStyle).not.toHaveBeenCalled()
  })

  it('renders not found for a missing style', async () => {
    vi.mocked(client.getStyle).mockRejectedValue(
      new client.ApiError('missing', 'NotFoundError', 404),
    )
    renderPage('/styles/5/edit')

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })

  it('retries an edit load failure and updates the title', async () => {
    const user = userEvent.setup()
    vi.mocked(client.getStyle)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(EXISTING_STYLE)
    renderPage('/styles/5/edit')

    await waitFor(() => expect(document.title).toBe('Edit Style | LoreCraft3000'))
    await user.click(await screen.findByRole('button', { name: 'Retry' }))
    expect(await screen.findByDisplayValue('Ink Wash')).toBeInTheDocument()
    await waitFor(() => expect(document.title).toBe('Edit Ink Wash | LoreCraft3000'))
  })

  it('uses the styles destination for clean and dirty Cancel navigation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    const user = userEvent.setup()
    const router = renderPage('/styles/new')

    await user.type(screen.getByLabelText('Name'), 'Charcoal')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(router.state.location.pathname).toBe('/styles/new')
    expect(screen.getByLabelText('Name')).toHaveValue('Charcoal')

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/styles'))
  })

  it('treats a hydrated edit form as clean', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    const router = renderPage('/styles/5/edit')

    await screen.findByDisplayValue('Ink Wash')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(router.state.location.pathname).toBe('/styles')
    expect(confirm).not.toHaveBeenCalled()
  })

  it('keeps a failed save dirty and bypasses navigation protection after success', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    vi.mocked(client.createStyle)
      .mockRejectedValueOnce(new Error('save failed'))
      .mockResolvedValueOnce({ ...EXISTING_STYLE, id: 9 })
    const router = renderPage('/styles/new')

    await user.type(screen.getByLabelText('Name'), 'Charcoal')
    const beforeUnload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(beforeUnload)
    expect(beforeUnload.defaultPrevented).toBe(true)

    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('save failed')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(router.state.location.pathname).toBe('/styles/new')
    expect(confirm).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/styles'))
    expect(confirm).toHaveBeenCalledTimes(1)
  })
})
