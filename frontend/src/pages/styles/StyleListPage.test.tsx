import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import * as client from '../../api/client'
import type { Style } from '../../api/types'
import { StyleListPage } from './StyleListPage'

vi.mock('../../api/client', async () => {
  const actual = await vi.importActual<typeof import('../../api/client')>('../../api/client')
  return {
    ...actual,
    listStyles: vi.fn(),
    listArchivedStyles: vi.fn(),
    archiveStyle: vi.fn(),
    restoreStyle: vi.fn(),
  }
})

const mockNavigate = vi.fn()
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom')
  return { ...actual, useNavigate: () => mockNavigate }
})

const STYLE: Style = {
  id: 5,
  name: 'Ink Wash',
  style_contract: 'Loose ink wash, high contrast.',
  created_at: '',
  archived_at: null,
}

const ARCHIVED_STYLE: Style = {
  id: 9,
  name: 'Retro Poster',
  style_contract: 'Bold flat colors.',
  created_at: '',
  archived_at: '2026-01-01T00:00:00Z',
}

describe('StyleListPage — archive & restore', () => {
  beforeEach(() => {
    mockNavigate.mockReset()
    vi.mocked(client.listStyles).mockReset().mockResolvedValue([STYLE])
    vi.mocked(client.listArchivedStyles).mockReset().mockResolvedValue([])
    vi.mocked(client.archiveStyle).mockReset().mockResolvedValue(undefined)
    vi.mocked(client.restoreStyle).mockReset()
  })

  it('opens edit when the whole style tile is clicked', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter>
        <StyleListPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: 'Edit Ink Wash' }))
    expect(mockNavigate).toHaveBeenCalledWith('/styles/5/edit')
    expect(screen.queryByRole('link', { name: 'Edit' })).not.toBeInTheDocument()
  })
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('archives a style after confirmation and reloads', async () => {
    const user = userEvent.setup()
    vi.mocked(client.listStyles).mockResolvedValueOnce([STYLE]).mockResolvedValueOnce([])
    render(
      <MemoryRouter>
        <StyleListPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /Delete/ }))
    expect(mockNavigate).not.toHaveBeenCalled()
    await user.click(await screen.findByRole('button', { name: 'Archive style' }))

    await waitFor(() => expect(client.archiveStyle).toHaveBeenCalledWith(5))
    await waitFor(() => expect(screen.queryByText('Ink Wash')).not.toBeInTheDocument())
  })

  it('lists archived styles and restores them', async () => {
    const user = userEvent.setup()
    vi.mocked(client.listArchivedStyles).mockResolvedValue([ARCHIVED_STYLE])
    vi.mocked(client.restoreStyle).mockResolvedValue({ ...ARCHIVED_STYLE, archived_at: null })
    render(
      <MemoryRouter>
        <StyleListPage />
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: /Show archived styles/ }))
    await user.click(await screen.findByRole('button', { name: 'Restore' }))

    await waitFor(() => expect(client.restoreStyle).toHaveBeenCalledWith(9))
  })
})
