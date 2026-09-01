import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { RouterProvider, createMemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { Character } from '../../api/types'
import { CharacterDetailPage } from './CharacterDetailPage'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    getCharacter: vi.fn(),
    listRefSets: vi.fn(),
    createRefSetDraft: vi.fn(),
  }
})

const CHARACTER: Character = {
  id: 1,
  name: 'Elias',
  slug: 'elias',
  lore_md: '',
  visual_contract: '',
  negative_traits: '',
  default_style_id: null,
  created_at: '',
  has_canonical_ref_set: false,
  avatar_url: null,
  avatar_initials: 'EL',
}

function renderPage(path: string) {
  const router = createMemoryRouter(
    [{ path: '/characters/:id', element: <CharacterDetailPage /> }],
    { initialEntries: [path] },
  )
  return { router, ...render(<RouterProvider router={router} />) }
}

describe('CharacterDetailPage routing', () => {
  beforeEach(() => {
    vi.mocked(client.getCharacter).mockReset().mockResolvedValue(CHARACTER)
    vi.mocked(client.listRefSets).mockReset().mockResolvedValue([])
    vi.mocked(client.createRefSetDraft).mockReset()
  })

  it('rejects malformed IDs without resource requests', async () => {
    renderPage('/characters/not-an-id')

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
    expect(client.getCharacter).not.toHaveBeenCalled()
    expect(client.listRefSets).not.toHaveBeenCalled()
  })

  it('renders not found for an API 404', async () => {
    vi.mocked(client.getCharacter).mockRejectedValue(
      new client.ApiError('missing', 'NotFoundError', 404),
    )
    renderPage('/characters/1')

    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeInTheDocument()
  })

  it('shows a retryable load error and updates the loaded title', async () => {
    const user = userEvent.setup()
    vi.mocked(client.getCharacter)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(CHARACTER)
    renderPage('/characters/1')

    await waitFor(() => expect(document.title).toBe('Loading Character | LoreCraft3000'))
    await user.click(await screen.findByRole('button', { name: 'Retry' }))

    expect(await screen.findByRole('heading', { name: 'Elias' })).toBeInTheDocument()
    await waitFor(() => expect(document.title).toBe('Elias | LoreCraft3000'))
  })

  it('keeps character content visible when reference sets fail and retries the section', async () => {
    const user = userEvent.setup()
    vi.mocked(client.listRefSets)
      .mockRejectedValueOnce(new Error('reference service offline'))
      .mockResolvedValueOnce([])
    renderPage('/characters/1')

    expect(await screen.findByRole('heading', { name: 'Elias' })).toBeInTheDocument()
    expect(screen.getByText(/Could not load reference sets: Error: reference service offline/)).toHaveAttribute(
      'role',
      'alert',
    )

    await user.click(screen.getByRole('button', { name: 'Retry reference sets' }))

    expect(await screen.findByText('No reference sets yet.')).toBeInTheDocument()
    expect(client.listRefSets).toHaveBeenCalledTimes(2)
  })

  it('ignores an older response after a rapid ID transition', async () => {
    let resolveFirst: (character: Character) => void = () => undefined
    vi.mocked(client.getCharacter).mockImplementation((id) => {
      if (id === 1) {
        return new Promise((resolve) => {
          resolveFirst = resolve
        })
      }
      return Promise.resolve({ ...CHARACTER, id: 2, name: 'Mara', slug: 'mara' })
    })
    const { router } = renderPage('/characters/1')
    await waitFor(() => expect(client.getCharacter).toHaveBeenCalledWith(1))

    await router.navigate('/characters/2')
    expect(await screen.findByRole('heading', { name: 'Mara' })).toBeInTheDocument()
    resolveFirst(CHARACTER)

    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Elias' })).not.toBeInTheDocument())
    expect(screen.getByRole('heading', { name: 'Mara' })).toBeInTheDocument()
  })

  it('keeps the loaded character visible when creating a draft fails', async () => {
    const user = userEvent.setup()
    vi.mocked(client.createRefSetDraft).mockRejectedValue(new Error('offline'))
    renderPage('/characters/1')

    await user.click(await screen.findByRole('button', { name: 'New draft' }))

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Could not create reference-set draft: Error: offline',
    )
    expect(screen.getByRole('heading', { name: 'Elias' })).toBeInTheDocument()
    expect(screen.getByText('No reference sets yet.')).toBeInTheDocument()
  })
})
