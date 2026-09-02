import { render, screen } from '@testing-library/react'
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

describe('CharacterListPage', () => {
  beforeEach(() => {
    vi.mocked(client.listCharacters).mockReset().mockResolvedValue([CHARACTER])
    vi.mocked(client.listArchivedCharacters).mockReset().mockResolvedValue([])
  })
  afterEach(() => vi.restoreAllMocks())

  it('uses the whole tile as the detail link with no redundant actions', async () => {
    render(
      <MemoryRouter>
        <CharacterListPage />
      </MemoryRouter>,
    )

    expect(await screen.findByRole('link', { name: /Mara/ })).toHaveAttribute(
      'href',
      '/characters/4',
    )
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  })

  it('links archived tiles to detail so they can be restored there', async () => {
    const user = userEvent.setup()
    vi.mocked(client.listArchivedCharacters).mockResolvedValue([ARCHIVED_CHARACTER])
    render(
      <MemoryRouter>
        <CharacterListPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /Show archived characters/ }))
    expect(screen.getByRole('link', { name: /Old Hero/ })).toHaveAttribute(
      'href',
      '/characters/8',
    )
  })
})
