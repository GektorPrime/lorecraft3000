import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { Character, Style } from '../../api/types'
import { CharacterFormPage } from './CharacterFormPage'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    createCharacter: vi.fn(),
    getCharacter: vi.fn(),
    listStyles: vi.fn(),
    updateCharacter: vi.fn(),
  }
})

const CHARACTER: Character = {
  id: 4,
  name: 'Mara',
  slug: 'mara',
  lore_md: '',
  visual_contract: '',
  negative_traits: '',
  default_style_id: null,
  created_at: '',
  has_canonical_ref_set: false,
  avatar_url: null,
  avatar_initials: 'MA',
}

function renderPage(path: string) {
  const router = createMemoryRouter(
    [
      { path: '/characters/new', element: <CharacterFormPage /> },
      { path: '/characters/:id/edit', element: <CharacterFormPage /> },
      { path: '/characters/:id', element: <h1>Character detail</h1> },
      { path: '/characters', element: <h1>Characters</h1> },
    ],
    { initialEntries: [path] },
  )
  render(<RouterProvider router={router} />)
  return router
}

describe('CharacterFormPage edit routing', () => {
  beforeEach(() => {
    vi.mocked(client.getCharacter).mockReset().mockResolvedValue(CHARACTER)
    vi.mocked(client.listStyles).mockReset().mockResolvedValue([])
    vi.mocked(client.createCharacter).mockReset().mockResolvedValue({ ...CHARACTER, id: 9 })
    vi.mocked(client.updateCharacter).mockReset().mockResolvedValue(CHARACTER)
  })
  afterEach(() => vi.restoreAllMocks())

  it('does not load form resources for a malformed edit ID', async () => {
    renderPage('/characters/bad/edit')

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(client.getCharacter).not.toHaveBeenCalled()
    expect(client.listStyles).not.toHaveBeenCalled()
  })

  it('handles 404 and retryable edit failures', async () => {
    const user = userEvent.setup()
    vi.mocked(client.getCharacter)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(CHARACTER)
    renderPage('/characters/4/edit')

    await waitFor(() => expect(document.title).toBe('Edit Character | LoreCraft3000'))
    await user.click(await screen.findByRole('button', { name: 'Retry' }))
    expect(await screen.findByDisplayValue('Mara')).toBeInTheDocument()
    await waitFor(() => expect(document.title).toBe('Edit Mara | LoreCraft3000'))
  })

  it('renders not found for a missing character', async () => {
    vi.mocked(client.getCharacter).mockRejectedValue(
      new client.ApiError('missing', 'NotFoundError', 404),
    )
    renderPage('/characters/4/edit')

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })

  it('treats create defaults and hydrated edit data as clean with the planned destinations', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    const createRouter = renderPage('/characters/new')

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(createRouter.state.location.pathname).toBe('/characters')
    expect(confirm).not.toHaveBeenCalled()

    const editRouter = renderPage('/characters/4/edit')
    await screen.findByDisplayValue('Mara')
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(editRouter.state.location.pathname).toBe('/characters/4')
    expect(confirm).not.toHaveBeenCalled()
  })

  it('preserves dirty values when Cancel is declined and leaves after confirmation', async () => {
    vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true)
    const user = userEvent.setup()
    const router = renderPage('/characters/new')
    const name = screen.getByLabelText('Name')

    await user.type(name, 'Elias')
    const cancel = screen.getByRole('button', { name: 'Cancel' })
    await user.click(cancel)
    expect(router.state.location.pathname).toBe('/characters/new')
    expect(name).toHaveValue('Elias')
    expect(cancel).toHaveFocus()

    await user.click(cancel)
    await waitFor(() => expect(router.state.location.pathname).toBe('/characters'))
  })

  it('keeps failed submissions dirty and bypasses protection only after a successful save', async () => {
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const user = userEvent.setup()
    vi.mocked(client.createCharacter)
      .mockRejectedValueOnce(new Error('save failed'))
      .mockResolvedValueOnce({ ...CHARACTER, id: 9 })
    const router = renderPage('/characters/new')

    await user.type(screen.getByLabelText('Name'), 'Elias')
    const beforeUnload = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(beforeUnload)
    expect(beforeUnload.defaultPrevented).toBe(true)
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(await screen.findByText(/save failed/)).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toHaveValue('Elias')

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(router.state.location.pathname).toBe('/characters/new')
    expect(confirm).toHaveBeenCalledTimes(1)

    await user.click(screen.getByRole('button', { name: 'Save' }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/characters/9'))
    expect(confirm).toHaveBeenCalledTimes(1)
  })

  it('shows a retryable style-list failure without discarding form values', async () => {
    const user = userEvent.setup()
    const style: Style = { id: 3, name: 'Charcoal', style_contract: '', created_at: '' }
    vi.mocked(client.listStyles)
      .mockRejectedValueOnce(new Error('styles offline'))
      .mockResolvedValueOnce([style])
    renderPage('/characters/new')

    await user.type(screen.getByLabelText('Name'), 'Elias')
    expect(await screen.findByRole('alert')).toHaveTextContent('styles offline')
    await user.click(screen.getByRole('button', { name: 'Retry styles' }))

    expect(await screen.findByRole('option', { name: 'Charcoal' })).toBeInTheDocument()
    expect(screen.getByLabelText('Name')).toHaveValue('Elias')
  })

  it('lets an in-flight save finish without navigating after the form is left', async () => {
    let resolveSave!: (character: Character) => void
    vi.mocked(client.createCharacter).mockReturnValue(
      new Promise((resolve) => {
        resolveSave = resolve
      }),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const user = userEvent.setup()
    const router = renderPage('/characters/new')

    await user.type(screen.getByLabelText('Name'), 'Elias')
    await user.click(screen.getByRole('button', { name: 'Save' }))
    expect(document.querySelector('form')).toHaveAttribute('aria-busy', 'true')
    await router.navigate('/characters')
    await waitFor(() => expect(router.state.location.pathname).toBe('/characters'))

    await act(async () => resolveSave({ ...CHARACTER, id: 9 }))
    expect(router.state.location.pathname).toBe('/characters')
  })
})
