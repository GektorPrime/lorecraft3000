import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { Character } from '../../api/types'
import { CharacterListPage } from './CharacterListPage'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    listCharacters: vi.fn(),
    listArchivedCharacters: vi.fn(),
    archiveCharacter: vi.fn(),
    restoreCharacter: vi.fn(),
  }
})

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
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
  archived_at: null,
  has_canonical_ref_set: false,
  avatar_url: null,
  avatar_initials: 'MA',
}

const ARCHIVED_CHARACTER: Character = {
  ...CHARACTER,
  id: 8,
  name: 'Old Hero',
  slug: 'old-hero',
  archived_at: '2026-01-01T00:00:00Z',
}

describe('CharacterListPage — tile click, archive & restore', () => {
  beforeEach(() => {
    mockNavigate.mockReset()
    vi.mocked(client.listCharacters).mockReset().mockResolvedValue([CHARACTER])
    vi.mocked(client.listArchivedCharacters).mockReset().mockResolvedValue([])
    vi.mocked(client.archiveCharacter).mockReset().mockResolvedValue(undefined)
    vi.mocked(client.restoreCharacter).mockReset()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('opens the character detail when the tile is clicked', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <CharacterListPage />
      </MemoryRouter>,
    )
    await user.click(await screen.findByRole('button', { name: /Open Mara/ }))
    expect(mockNavigate).toHaveBeenCalledWith('/characters/4')
  })

  it('does not open detail when an action button is clicked', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <CharacterListPage />
      </MemoryRouter>,
    )
    await screen.findByText('Mara')
    await user.click(screen.getByRole('link', { name: /Edit/ }))
    expect(mockNavigate).not.toHaveBeenCalledWith('/characters/4')
  })

  it('archives a character after confirmation and reloads', async () => {
    const user = userEvent.setup()
    vi.mocked(client.listCharacters).mockResolvedValueOnce([CHARACTER]).mockResolvedValueOnce([])
    render(
      <MemoryRouter>
        <CharacterListPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /Delete/ }))
    await user.click(await screen.findByRole('button', { name: 'Archive character' }))

    await waitFor(() => expect(client.archiveCharacter).toHaveBeenCalledWith(4))
    await waitFor(() => expect(screen.queryByText('Mara')).not.toBeInTheDocument())
    expect(mockNavigate).not.toHaveBeenCalledWith('/characters/4')
  })

  it('lists archived characters and restores them', async () => {
    const user = userEvent.setup()
    vi.mocked(client.listArchivedCharacters).mockResolvedValue([ARCHIVED_CHARACTER])
    vi.mocked(client.restoreCharacter).mockResolvedValue({ ...ARCHIVED_CHARACTER, archived_at: null })
    render(
      <MemoryRouter>
        <CharacterListPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /Show archived characters/ }))
    await user.click(await screen.findByRole('button', { name: 'Restore' }))

    await waitFor(() => expect(client.restoreCharacter).toHaveBeenCalledWith(8))
  })
})
